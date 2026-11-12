from dataclasses import dataclass
from pathlib import Path
import base64
import os


@dataclass(frozen=True)
class Settings:
    token: str
    ledger_key: bytes
    ledger_path: Path
    live_enabled: bool = False
    username: str = ""
    password: str = ""
    province_code: str = ""
    province_name: str = ""
    city_code: str = ""
    city_name: str = ""
    ocr_base_url: str = ""
    ocr_api_key: str = ""
    ocr_model: str = ""

    @classmethod
    def from_env(cls):
        token = os.environ.get("TK_GATEWAY_TOKEN", "")
        if len(token) < 32 or token.startswith("change-"):
            raise RuntimeError("TK_GATEWAY_TOKEN must be a new random secret of at least 32 characters")
        try:
            key = base64.b64decode(os.environ.get("TK_LEDGER_KEY", ""), validate=True)
        except ValueError:
            key = b""
        if len(key) != 32:
            raise RuntimeError("TK_LEDGER_KEY must be a base64-encoded random 32-byte AES key")
        return cls(
            token=token,
            ledger_key=key,
            ledger_path=Path(os.environ.get("TK_LEDGER_PATH", "./var/requests.sqlite3")),
            live_enabled=os.environ.get("TK_LIVE_ENABLED", "false").lower() == "true",
            username=os.environ.get("TK_USERNAME", ""),
            password=os.environ.get("TK_PASSWORD", ""),
            province_code=os.environ.get("TK_PROVINCE_CODE", ""),
            province_name=os.environ.get("TK_PROVINCE_NAME", ""),
            city_code=os.environ.get("TK_CITY_CODE", ""),
            city_name=os.environ.get("TK_CITY_NAME", ""),
            ocr_base_url=os.environ.get("OCR_BASE_URL", "").rstrip("/"),
            ocr_api_key=os.environ.get("OCR_API_KEY", ""),
            ocr_model=os.environ.get("OCR_MODEL", ""),
        )

    def validate_carrier(self):
        if not self.live_enabled:
            raise ValueError("未启用真实泰康报价，请配置 TK_LIVE_ENABLED 后由管理员检查登录。")
        if not self.username or not self.password:
            raise ValueError("泰康账号未配置，请联系管理员。")
        values = (self.province_code, self.province_name, self.city_code, self.city_name)
        if not all(values) or not self.province_code.isdigit() or not self.city_code.isdigit():
            raise ValueError("泰康报价省市未配置，请填写实际承保地区。")
        if len(self.province_code) != 6 or len(self.city_code) != 6:
            raise ValueError("泰康地区代码格式不正确。")

    def business_settings(self):
        area = {"provinceCode": self.province_code, "provinceName": self.province_name,
                "cityCode": self.city_code, "cityName": self.city_name}
        return {"quoteArea": dict(area), "insuredArea": dict(area)}
