"""Per-OCR-lane transport timings, no global patches, payload capture or retries.

Response timing means complete response headers, not first-byte wire capture.
A reused TLS connection has no new connect timing. Missing events remain absent.
"""

from contextlib import contextmanager
from contextvars import ContextVar
import time
import re
from datetime import datetime, timezone

from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPSConnection
from urllib3.connectionpool import HTTPSConnectionPool

_current = ContextVar("tk_ocr_transport", default=None)


class OcrTiming:
    def __init__(self):
        self.started = time.monotonic()
        self.phase = "CONNECT_OR_SEND"
        self.points = {}
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.response_status = None
        self.request_ids = {}

    def mark(self, name, phase):
        self.points[name] = round((time.monotonic() - self.started) * 1000)
        self.phase = phase

    def facts(self):
        result = {"phase": self.phase, "startedAt": self.started_at, **self.points}
        if self.response_status is not None:
            result["responseHttpStatus"] = self.response_status
        if self.request_ids:
            result["supplierRequestIds"] = dict(self.request_ids)
        return result


@contextmanager
def observe_ocr():
    timing = OcrTiming()
    token = _current.set(timing)
    try:
        yield timing
    finally:
        _current.reset(token)


class TimedHTTPSConnection(HTTPSConnection):
    def connect(self):
        timing = _current.get()
        if timing:
            timing.mark("connectStartedMs", "CONNECT")
        super().connect()
        if timing:
            timing.mark("connectCompletedMs", "UPLOAD")

    def send(self, data):
        timing = _current.get()
        if timing:
            timing.phase = "UPLOAD"
        super().send(data)
        if timing:
            timing.mark("lastSendCompletedMs", "UPLOAD")

    def getresponse(self):
        timing = _current.get()
        if timing:
            timing.mark("uploadCompletedMs", "WAITING_RESPONSE_HEADERS")
        response = super().getresponse()
        if timing:
            timing.mark("responseHeadersMs", "READING_BODY")
            status = getattr(response, "status", None)
            if isinstance(status, int) and 100 <= status <= 599:
                timing.response_status = status
            headers = getattr(response, "headers", {})
            for header in ("x-request-id", "x-correlation-id", "traceparent"):
                value = headers.get(header)
                if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value):
                    timing.request_ids[header] = value
        return response


class TimedHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = TimedHTTPSConnection


class OcrTimingAdapter(HTTPAdapter):
    @staticmethod
    def _instrument(manager):
        # urllib3's default mapping is shared: always copy before replacing HTTPS.
        manager.pool_classes_by_scheme = dict(manager.pool_classes_by_scheme)
        manager.pool_classes_by_scheme["https"] = TimedHTTPSPool

    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self._instrument(self.poolmanager)

    def proxy_manager_for(self, *args, **kwargs):
        manager = super().proxy_manager_for(*args, **kwargs)
        self._instrument(manager)
        return manager


def active_timing():
    return _current.get()
