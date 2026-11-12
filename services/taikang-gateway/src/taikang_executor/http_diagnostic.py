"""Transport facts only: never serialize credentials, payloads or exception arguments."""

import errno
import hashlib
import re


def exception_chain(error):
    pending = [error]
    seen = set()
    result = []
    while pending and len(result) < 16:
        current = pending.pop(0)
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        seen.add(id(current))
        item = {"type": type(current).__name__, "module": type(current).__module__}
        for key in ("errno", "winerror"):
            value = getattr(current, key, None)
            if isinstance(value, int) and not isinstance(value, bool):
                item[key] = value
                if key == "errno" and value in errno.errorcode:
                    item["errnoName"] = errno.errorcode[value]
        result.append(item)
        pending.extend([current.__cause__, current.__context__, getattr(current, "reason", None)])
        pending.extend(value for value in current.args if isinstance(value, BaseException))
    return result


def request_facts(path, response, elapsed_ms, error=None):
    facts = {"method": "POST", "path": path, "elapsedMs": elapsed_ms, "hasResponse": response is not None}
    if response is not None:
        facts["httpStatus"] = response.status_code
        mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        facts["contentType"] = mime if re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", mime) else None
        facts["responseBytes"] = len(response.content)
        facts["responseSha256"] = hashlib.sha256(response.content).hexdigest()
        ids = {}
        for header in ("x-request-id", "x-correlation-id", "traceparent"):
            value = response.headers.get(header)
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value):
                ids[header] = value
        if ids:
            facts["supplierRequestIds"] = ids
        facts["redirectStatuses"] = [item.status_code for item in response.history]
    else:
        facts["httpStatus"] = None
    if error is not None:
        facts["exceptionChain"] = exception_chain(error)
    return facts
