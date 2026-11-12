import re
import threading


class CaptchaRecognizer:
    _lock = threading.Lock()
    _engine = None

    @classmethod
    def _get_engine(cls):
        with cls._lock:
            if cls._engine is None:
                import ddddocr

                cls._engine = ddddocr.DdddOcr(show_ad=False)
            return cls._engine

    def predict(self, image_bytes: bytes) -> str:
        value = self._get_engine().classification(image_bytes)
        return re.sub(r"[^0-9A-Za-z]", "", value or "")[:4]
