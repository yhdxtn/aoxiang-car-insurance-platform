import base64
import binascii
import copy
import json
import random
import re
import time
import uuid
from pathlib import Path

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

from taikang_executor.captcha import CaptchaRecognizer
from taikang_executor.http_diagnostic import request_facts
from taikang_executor.ocr_transport import active_timing


class TkApiError(RuntimeError):
    pass


class TkSessionExpired(TkApiError):
    """Confirmed authentication expiry, not a transport or underwriting failure."""

    def __init__(self):
        super().__init__("泰康登录状态已过期，已请求恢复登录；本笔未自动重报或重提投保")


class TkTransportError(TkApiError):
    def __init__(self, diagnostic):
        self.transport_diagnostic = diagnostic
        super().__init__("泰康接口请求异常：" + diagnostic["path"])


class TkModelAmbiguous(TkApiError):
    def __init__(self, candidates, stage=None):
        super().__init__("车型候选需要人工确认")
        self.candidates = [
            {"modelCode": str(item.get("modelCode") or "")[:200], "modelName": str(item.get("modelName") or "")[:200]}
            for item in candidates[:20]
            if item.get("modelCode")
        ]
        self.stage = stage


def choose_model(candidates, selected_model_code=None, stage=None):
    if isinstance(selected_model_code, dict):
        selected_model_code = selected_model_code.get(stage)
    if not candidates:
        raise TkApiError("没有查询到匹配的车辆型号")
    if selected_model_code:
        selected = [item for item in candidates if str(item.get("modelCode")) == selected_model_code]
        if len(selected) == 1:
            return selected[0]
        raise TkModelAmbiguous(candidates, stage)
    if len(candidates) == 1:
        return candidates[0]
    raise TkModelAmbiguous(candidates, stage)


class TkApiClient:
    @staticmethod
    def _actual_color_code(driving, supplier):
        # Exact supplier select options verified from basicInfo.html. No visual inference.
        colors = {
            "白色": "001",
            "灰色": "002",
            "黄色": "003",
            "粉色": "004",
            "红色": "005",
            "紫色": "006",
            "绿色": "007",
            "蓝色": "008",
            "棕色": "009",
            "黑色": "010",
            "其他": "999",
        }
        sources = [driving, supplier.get("carInfoDto") or {}, supplier.get("carInfoVo") or {}]
        for source in sources:
            if not isinstance(source, dict):
                continue
            for key in ("colorCode", "bodyColor"):
                value = source.get(key)
                if isinstance(value, str):
                    value = value.strip()
                    if value in colors.values():
                        return value
                    if value in colors:
                        return colors[value]
        return "999"

    BASE_URL = "https://car.tk.cn/carSelfService"
    CHANNEL = "OffWeb"
    PASSWORD_KEY = b"hh43jii5e954eD54"
    DATA_KEY = b"MP5t1OVqJCBALNKc"
    DATA_IV = b"A9CAED282E409002"

    DEFAULT_PROVINCE = {}
    DEFAULT_CITY = {}

    def __init__(self, logger=None, captcha_callback=None):
        self.logger = logger or (lambda _message: None)
        self.captcha_callback = captcha_callback or (lambda _image, _code: None)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/140.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "Origin": "https://car.tk.cn",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
        )
        self.username = ""
        self.tk_token = ""
        self.carss_token = ""
        self.tplatform_id = ""
        self.tplat_login_key = ""
        self.order_id = ""
        self.user_info = {}
        self.from_id = "84942"
        self.com_code = "0153"
        self.retrospect_id = ""
        self.quote_context = {}
        self.quote_result = {}
        self.last_http_diagnostic = None
        self.http_diagnostics = []

    @staticmethod
    def encrypt_password(password: str) -> str:
        cipher = AES.new(TkApiClient.PASSWORD_KEY, AES.MODE_ECB)
        return base64.b64encode(cipher.encrypt(pad(password.encode("utf-8"), 16))).decode("ascii")

    @staticmethod
    def decrypt_business_data(value: str):
        if isinstance(value, (dict, list)):
            return value
        if not isinstance(value, str) or not value.strip():
            raise TkApiError("业务数据为空，无法解密")

        value = value.strip()
        if value[:1] in {"{", "["}:
            try:
                return json.loads(value)
            except json.JSONDecodeError as exc:
                raise TkApiError("业务数据是无效的 JSON") from exc

        encrypted = None
        compact = re.sub(r"\s+", "", value)
        if len(compact) % 2 == 0 and re.fullmatch(r"[0-9a-fA-F]+", compact):
            encrypted = bytes.fromhex(compact)
        else:
            try:
                encrypted = base64.b64decode(compact, validate=True)
            except (ValueError, binascii.Error):
                encrypted = None

        if not encrypted or len(encrypted) % AES.block_size:
            raise TkApiError("接口返回了无法识别的业务数据格式")
        try:
            cipher = AES.new(TkApiClient.DATA_KEY, AES.MODE_CBC, TkApiClient.DATA_IV)
            text = unpad(cipher.decrypt(encrypted), AES.block_size).decode("utf-8")
            return json.loads(text)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TkApiError("接口业务数据解密失败") from exc

    @staticmethod
    def _flow_id(prefix="carInsur"):
        suffix = f"{int(time.time() * 1000)}{random.randint(1000000, 9999999)}"
        return prefix + suffix

    def _headers(self, referer: str, *, xhr=True, action_type=None):
        headers = {
            "Referer": referer,
            "channelCode": self.CHANNEL,
            "grayFlag": "pro",
            "carInsurFlowId": self._flow_id("carInsur" if self.username else "offwebNew"),
            "carInsurOrderId": self.order_id or self.username or "null",
            "carssToken": self.carss_token,
            # The HAR uses tplatLoginKey in the userId header.
            "userId": self.tplat_login_key,
        }
        if xhr:
            headers["X-Requested-With"] = "XMLHttpRequest"
        if self.tk_token:
            headers["tkCarRequestToken"] = self.tk_token
        if action_type:
            headers["actionType"] = action_type
        return headers

    def _post(self, path: str, body: dict, *, referer: str, xhr=True, action_type=None):
        started = time.monotonic()
        response = None
        if (timing := active_timing()) is not None:
            timing.mark("requestStartedMs", "CONNECT_OR_SEND")
        try:
            response = self.session.post(
                self.BASE_URL + path,
                json=body,
                headers=self._headers(referer, xhr=xhr, action_type=action_type),
                timeout=getattr(self, "request_timeout", (15, 120)),
            )
            if (timing := active_timing()) is not None:
                timing.mark("readCompletedMs", "PARSING_RESPONSE")
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            if response is None:
                response = getattr(exc, "response", None)
            facts = request_facts(path, response, round((time.monotonic() - started) * 1000), exc)
            if (timing := active_timing()) is not None:
                facts["timings"] = timing.facts()
                if timing.response_status is not None:
                    facts["httpStatus"] = timing.response_status
                    facts["responseHeadersReceived"] = True
                if timing.request_ids:
                    facts["supplierRequestIds"] = dict(timing.request_ids)
            self.last_http_diagnostic = facts
            self.http_diagnostics = (self.http_diagnostics + [facts])[-16:]
            raise TkTransportError(facts) from exc
        self.last_http_diagnostic = request_facts(path, response, round((time.monotonic() - started) * 1000))
        if (timing := active_timing()) is not None:
            timing.phase = "COMPLETED"
            self.last_http_diagnostic["timings"] = timing.facts()
        self.http_diagnostics = (self.http_diagnostics + [self.last_http_diagnostic])[-16:]
        return payload

    def reset_transport_pool(self):
        """Discard idle sockets without changing cookies, tokens, or login identity.

        The account cache invokes this only while holding its account lock, between
        stages or after a failed request has unwound. No request is retried here.
        """
        for adapter in self.session.adapters.values():
            adapter.close()

    @staticmethod
    def _message(payload):
        return payload.get("message") or payload.get("msg") or "接口返回失败状态"

    @staticmethod
    def _choose_model(candidates, selected_model_code=None, stage=None):
        return choose_model(candidates, selected_model_code, stage)

    @classmethod
    def _require_success(cls, payload, stage):
        if str(payload.get("status", "1")) != "1":
            raise TkApiError(f"{stage}失败：{cls._message(payload)}")
        return payload

    def _identity(self, body, *, referer, xhr=True):
        result = self._post("/rest/controller/identity", body, referer=referer, xhr=xhr)
        self._require_success(result, "获取请求令牌")
        self.tk_token = result.get("data", {}).get("tkCarRequestToken", "")
        if not self.tk_token:
            raise TkApiError("获取请求令牌失败：响应中没有 tkCarRequestToken")
        return result

    def login_and_prepare(self, username: str, password: str):
        """Legacy quote-only entry point; stage callers can reuse login separately."""
        self.login(username, password)
        return self.prepare_order()

    def login(self, username: str, password: str, *, use_captcha=True):
        self.username = username.strip()
        if not self.username or not password:
            raise TkApiError("请输入账号和密码")

        login_page = "https://car.tk.cn/offwebNew/"
        self.logger("建立泰康登录会话")
        try:
            page = self.session.get(login_page, timeout=(15, 60))
            page.raise_for_status()
        except requests.RequestException as exc:
            raise TkApiError(f"无法打开泰康登录页：{exc}") from exc
        self.logger("获取登录请求令牌")
        self._identity({"channelCode": self.CHANNEL}, referer=login_page, xhr=False)

        if use_captcha:
            recognizer = CaptchaRecognizer()
            captcha_code = ""
            for attempt in range(1, 6):
                self.logger(f"获取并识别验证码（第 {attempt} 次）")
                captcha = self._post(
                    "/rest/tplatform/getCaptcha",
                    {},
                    referer=login_page,
                    xhr=False,
                    action_type="queryClaimData",
                )
                self._require_success(captcha, "获取验证码")
                data_url = captcha.get("data", "")
                if "," not in data_url:
                    raise TkApiError("验证码响应格式不正确")
                try:
                    image_bytes = base64.b64decode(data_url.split(",", 1)[1])
                except ValueError as exc:
                    raise TkApiError("验证码图片解码失败") from exc

                captcha_code = recognizer.predict(image_bytes)
                self.captcha_callback(image_bytes, captcha_code)
                self.logger(f"验证码自动识别结果：{captcha_code or '未识别'}")
                if len(captcha_code) != 4:
                    continue

                checked = self._post(
                    "/rest/tplatform/checkCaptcha",
                    {"captchaCode": captcha_code},
                    referer=login_page,
                    xhr=False,
                    action_type="queryClaimData",
                )
                if str(checked.get("status")) == "1":
                    break
                self.logger("验证码校验未通过，自动刷新重试")
            else:
                raise TkApiError("连续 5 次自动识别验证码失败")

            self.logger("验证码通过，正在登录")
        login = self._post(
            "/rest/tplatform/login",
            {
                "userName": self.username,
                "channelCode": self.CHANNEL,
                "password": self.encrypt_password(password),
            },
            referer=login_page,
            xhr=False,
            action_type="queryClaimData",
        )
        self._require_success(login, "登录")
        data = login.get("data") or {}
        # The production branch in the captured front-end treats loginStatus "0"
        # as the normal, fully authenticated path.  "1" and "2" open extra
        # verification forms, while "3" means the daily verification limit.
        login_status = str(data.get("loginStatus", ""))
        if login_status in {"1", "2"}:
            raise TkApiError(
                "账号需要额外身份验证，当前 HAR 没有记录该分支："
                + (data.get("message") or f"loginStatus={login_status}")
            )
        if login_status == "3":
            raise TkApiError("验证码获取次数已超出限制，请次日再试")
        if login_status not in {"0", ""}:
            raise TkApiError(f"登录返回未知状态 {login_status}：{data.get('message') or '无说明'}")

        self.tplatform_id = data.get("tplatformId", "")
        self.tplat_login_key = data.get("tplatLoginKey", "")
        self.carss_token = data.get("carssToken", "")
        self.user_info = data.get("websysUserVo") or {}
        self.from_id = str(self.user_info.get("fromid") or self.from_id)
        areas = self.user_info.get("websysUserAreaVos") or []
        if areas and areas[0].get("areacode"):
            self.com_code = str(areas[0]["areacode"])
        if not all((self.tplatform_id, self.tplat_login_key, self.carss_token)):
            raise TkApiError("登录响应缺少会话字段，无法继续建单")

        self.logger("登录成功，初始化报价菜单")
        self._identity({"channelCode": self.CHANNEL}, referer=login_page, xhr=False)

        # These two calls mirror the login HAR. A notice failure does not block quoting.
        try:
            self._post(
                "/rest/groupOrder/getNewNoticeStatus",
                {"channelCode": self.CHANNEL, "tplatformId": self.tplatform_id},
                referer=login_page,
                xhr=False,
            )
        except TkApiError:
            pass
        menu = self._post(
            "/rest/tplatform/checkMenu",
            {
                "menuId": "7FF5E06998644B5FA0BB9AA73A0F7FB8",
                "tplatformId": self.tplatform_id,
                "accountId": self.username,
            },
            referer=login_page,
            xhr=False,
        )
        self._require_success(menu, "校验报价菜单权限")

        return {"display_name": self.user_info.get("usercnname") or self.username}

    def prepare_order(self):
        """Create a distinct external order without authenticating the account again."""
        if not all((self.username, self.tplatform_id, self.tplat_login_key, self.carss_token)):
            raise TkApiError("请先建立有效的泰康登录会话")
        if self.order_id:
            raise TkApiError("当前客户端已经绑定订单，不能覆盖已有订单")
        area_page = "https://car.tk.cn/offweb/views/page/areaInfo/areaInfo.html"
        self.verify_quote_token()
        self.logger("创建新报价订单")
        order = self._post(
            "/rest/controller/getOrderId",
            {"channelCode": self.CHANNEL},
            referer=area_page,
        )
        self._require_success(order, "创建订单")
        self.order_id = (order.get("data") or {}).get("orderId", "")
        if not self.order_id:
            raise TkApiError("创建订单失败：响应中没有 orderId")

        basic = self._post(
            "/rest/init/basicData",
            {"channelCode": self.CHANNEL},
            referer=area_page,
        )
        if not basic:
            raise TkApiError("加载报价基础数据失败")

        self.logger(f"登录和建单完成，订单号：{self.order_id}")
        return {
            "display_name": self.user_info.get("usercnname") or self.username,
            "order_id": self.order_id,
            "from_id": self.from_id,
            "com_code": self.com_code,
        }

    def verify_quote_token(self):
        """Verify the captured quotation token request without creating an order."""
        if not all((self.username, self.tplatform_id, self.tplat_login_key, self.carss_token)):
            raise TkApiError("请先建立有效的泰康登录会话")
        return self._identity(
            {"channelCode": self.CHANNEL, "tplatformId": self.tplatform_id, "userName": self.tplatform_id},
            referer="https://car.tk.cn/offweb/views/page/areaInfo/areaInfo.html",
        )

    def _base_area_info(self, license_no):
        return {
            "agent": {
                "comCode": self.com_code,
                "intermediaryName": "",
                "agentCode": "",
                "agentName": "",
                "agencyName": "",
                "agencyCode": "",
                "agentPhone": "",
                "hwpName": "",
            },
            "channelCode": self.CHANNEL,
            "orderID": self.order_id,
            "bjFlag": 0,
            "licenseNo": license_no,
            "isNewCarWithoutLicense": 0,
            "provinceName": self.DEFAULT_PROVINCE["name"],
            "provinceCode": self.DEFAULT_PROVINCE["code"],
            "cityName": self.DEFAULT_CITY["name"],
            "cityCode": self.DEFAULT_CITY["code"],
            "areaFlag": self.DEFAULT_CITY["code"],
            "comCode": self.com_code,
            "clientType": "",
            "fromID": self.from_id,
            "formID": self.from_id,
            "tplatformId": self.tplatform_id,
            "leadsId": "",
        }

    @staticmethod
    def _image_base64(path):
        file_path = Path(path)
        if not file_path.is_file():
            raise TkApiError(f"图片不存在：{file_path.name}")
        if file_path.stat().st_size > 15 * 1024 * 1024:
            raise TkApiError(f"图片过大（最大 15 MB）：{file_path.name}")
        return base64.b64encode(file_path.read_bytes()).decode("ascii")

    def _smart_ocr(self, path, expected_type, label, referer):
        self.logger(f"上传并识别{label}")
        result = self._post(
            "/rest/ocr/smartOcr",
            {
                "ocrDataDto": {},
                "extraInfo": {},
                "base64Imgs": [self._image_base64(path)],
                "channelCode": self.CHANNEL,
                "orderId": self.order_id,
                "fromId": self.from_id,
                "comCode": self.com_code,
                "tplatformId": self.tplatform_id,
                "imgTypes": "IdFront,Vehiclelicense,Subvehiclelicense",
                "relatedNature": "3",
            },
            referer=referer,
        )
        self._require_success(result, f"{label} OCR")
        actual = (result.get("data") or {}).get("sortType")
        if actual != expected_type:
            raise TkApiError(f"{label}图片类型不正确：服务端识别为 {actual or '未知类型'}")
        return result["data"]

    @staticmethod
    def _id_birth_and_sex(id_number):
        value = (id_number or "").strip()
        birth = ""
        sex = 1
        if len(value) == 18 and value[:17].isdigit():
            birth = f"{value[6:10]}-{value[10:12]}-{value[12:14]}"
            sex = 1 if int(value[16]) % 2 else 2
        return birth, sex

    @staticmethod
    def _numeric_text(value, default=""):
        """Convert values such as '7人' and '2070kg' to API numeric text."""
        match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
        if not match:
            return default
        number = match.group(0)
        return number[:-2] if number.endswith(".0") else number

    @staticmethod
    def _api_date(value):
        """Normalize OCR dates such as 20241005 to 2024-10-05."""
        digits = re.sub(r"\D", "", str(value or ""))
        if len(digits) == 8:
            return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
        return str(value or "")

    def quote(self, documents: dict, ocr_callback=None, selected_model_code=None):
        """Legacy default quote, retaining the quote-only executor contract."""
        self.prepare_quote(documents, ocr_callback, selected_model_code)
        return self.calculate_prepared_quote()

    def prepare_quote(self, documents: dict, ocr_callback=None, selected_model_code=None):
        if not self.order_id:
            raise TkApiError("请先登录并创建订单")
        required = ("vehicle_front", "vehicle_back", "id_front")
        if any(not documents.get(key) for key in required):
            raise TkApiError("请完整上传行驶证主页、行驶证副页和身份证人像面")
        basic_page = self._initialize_basic_page()

        front = self._smart_ocr(documents["vehicle_front"], "Vehiclelicense", "行驶证主页", basic_page)
        back = self._smart_ocr(documents["vehicle_back"], "Subvehiclelicense", "行驶证副页", basic_page)
        identity = self._smart_ocr(documents["id_front"], "IdFront", "身份证人像面", basic_page)

        driving = {}
        driving.update(front.get("DrivingLicense") or {})
        driving.update(back.get("DrivingLicense") or {})
        id_card = identity.get("IdCard") or {}
        driving, id_card = self._validated_ocr_fields(driving, id_card)
        if (
            getattr(self, "strict_document_fields", False)
            and getattr(self, "supplier_ocr_success_policy", None) != "SUPPLIER_OCR_SUCCESS_V1"
            and driving.get("brandNo")
            and not driving.get("brandNoBack")
        ):
            driving["brandNoBack"] = driving["brandNo"]
        from .supplier_evidence import identity_number

        owner_id = identity_number(id_card)
        license_no = driving.get("brandNo") or driving.get("brandNoBack") or ""
        vin = driving.get("VIN") or driving.get("vin") or ""
        supplier_ocr = getattr(self, "supplier_ocr_success_policy", None) == "SUPPLIER_OCR_SUCCESS_V1"
        if not supplier_ocr and not all((owner_id, license_no, vin, driving.get("engineNo"))):
            raise TkApiError("OCR 结果缺少证件号、车牌、VIN 或发动机号，请检查图片清晰度")

        enroll_date = self._api_date(driving.get("regDate", ""))
        issue_date = self._api_date(driving.get("issueDate", ""))
        seats = self._ocr_seats(driving)
        if (
            not supplier_ocr
            and getattr(self, "strict_document_fields", False)
            and (not driving.get("owner") or not id_card.get("name"))
        ):
            raise TkApiError("证件未返回完整车主和身份证姓名，不能替代确认身份")
        if (
            getattr(self, "strict_document_fields", False)
            and not supplier_ocr
            and driving.get("owner")
            and id_card.get("name")
            and driving["owner"].strip() != id_card["name"].strip()
        ):
            raise TkApiError("行驶证车主与身份证姓名不一致，需要人工核实身份")
        # The captured response stores the vehicle curb/kerb mass in
        # loadQualite (for example "2070kg"); curbWeight can be empty.
        curing_quality = self._numeric_text(
            (
                driving.get("loadQualite")
                if getattr(self, "consistency_policy", None) == "TK_OCR_CONSISTENCY_V5"
                else driving.get("curbWeight") or driving.get("loadQualite")
            ),
            "" if supplier_ocr else "0",
        )
        ocr_result = {
            "name": (id_card.get("name") or "") if supplier_ocr else id_card.get("name") or driving.get("owner") or "",
            "owner_name": driving.get("owner") or "",
            "id_name": id_card.get("name") or "",
            "id_number": owner_id,
            "license_no": license_no,
            "vin": vin,
            "engine_no": driving.get("engineNo", ""),
            "model_name": driving.get("brandModel", ""),
            "enroll_date": enroll_date,
        }
        if ocr_callback and seats:
            ocr_callback(ocr_result)

        self.logger("保存 OCR 预填信息")
        self._require_success(
            self._post(
                "/rest/ocr/saveOcrPrefillInfo",
                {
                    "channelCode": self.CHANNEL,
                    "orderId": self.order_id,
                    "fromId": self.from_id,
                    "saveRenewInfoFlag": "0",
                    "data": {
                        "drivingLicense": {
                            "issueDate": issue_date,
                            "carType": driving.get("carType", ""),
                            "address": driving.get("address", ""),
                            "properties": driving.get("properties", ""),
                            "brandModel": driving.get("brandModel", ""),
                            "owner": driving.get("owner", ""),
                            "regDate": enroll_date,
                            "engineNo": driving.get("engineNo", ""),
                            "brandNo": license_no,
                            **({"loadNumber": seats} if seats else {}),
                            "loadQualite": self._numeric_text(driving.get("loadQualite"), ""),
                            "curbWeight": self._numeric_text(driving.get("curbWeight"), ""),
                            "pullWeight": self._numeric_text(driving.get("pullWeight"), ""),
                            "fuelType": driving.get("fuelType", ""),
                            "vin": vin,
                        },
                        "carOwnerIdCard": {
                            "name": ocr_result["name"],
                            "id": owner_id,
                        },
                    },
                },
                referer=basic_page,
            ),
            "保存 OCR 信息",
        )

        return self._prepare_vehicle(
            driving,
            id_card,
            ocr_result,
            seats,
            curing_quality,
            enroll_date,
            selected_model_code,
            ocr_callback,
            basic_page,
        )

    def _initialize_basic_page(self):
        self.retrospect_id = str(uuid.uuid4())

        basic_page = f"https://car.tk.cn/offweb/views/page/basicInfo/basicInfo.html?fromId={self.from_id}"
        self.logger("初始化车辆和证件基础数据")
        self._identity(
            {
                "channelCode": self.CHANNEL,
                "tplatformId": self.tplatform_id,
                "userName": self.tplatform_id,
            },
            referer=basic_page,
        )
        self._post(
            "/rest/init/basicInfo",
            {
                "fromId": self.from_id,
                "channelCode": self.CHANNEL,
                "tplatformId": self.tplatform_id,
                "orderManageFlag": "null",
                "orderID": self.order_id,
                "requestId": "",
                "crossRenewalFlag": "",
                "tplatLoginKey": self.tplat_login_key,
            },
            referer=basic_page,
        )
        self._identity(
            {"channelCode": self.CHANNEL, "orderId": self.order_id},
            referer=basic_page,
        )
        self._post(
            "/rest/init/car/type",
            {
                "fromId": self.from_id,
                "comCode": self.com_code,
                "channelCode": self.CHANNEL,
                "tplatformId": self.tplatform_id,
            },
            referer=basic_page,
        )
        self._post(
            "/rest/init/identify",
            {
                "fromId": self.from_id,
                "channelCode": self.CHANNEL,
                "tplatformId": self.tplatform_id,
                "orderID": self.order_id,
                "comCode": self.com_code,
            },
            referer=basic_page,
        )

        return basic_page

    def _initial_model_data(self, body, basic_page):
        first_raw = self._post("/rest/car/modelinfo/query", body, referer=basic_page)
        if not isinstance(first_raw.get("data"), str):
            raise TkApiError("首次车型查询没有返回加密业务数据")
        first = self.decrypt_business_data(first_raw["data"])
        self._require_success(first, "首次车型查询")
        return first.get("data") or {}

    def _vehicle_query_mode(self):
        return "1"

    def _quote_ocr_flag(self):
        return 1

    def _query_vehicle_flag(self):
        return False

    def _prepare_vehicle(
        self,
        driving,
        id_card,
        ocr_result,
        seats,
        curing_quality,
        enroll_date,
        selected_model_code,
        ocr_callback,
        basic_page,
    ):
        transfer_fields = self._transfer_car_fields()
        enroll_date = self._confirmed_registration_date(enroll_date)
        ocr_result["enroll_date"] = enroll_date
        license_no, owner_id, vin = ocr_result["license_no"], ocr_result["id_number"], ocr_result["vin"]
        area_info = self._base_area_info(license_no)
        owner = {"name": ocr_result["name"], "id": owner_id}
        self.logger("按 OCR 字段查询车辆型号")
        first_query_body = {
            "orderID": self.order_id,
            "channelCode": self.CHANNEL,
            "carInfoVo": {
                "isQueryCarByOCR": "1",
                "carType": "A",
                "licenseNo": license_no,
                "modelName": driving.get("brandModel", ""),
                "enrollDate": enroll_date,
                "engineNo": driving.get("engineNo", ""),
                "vinNo": vin,
                "selectedSeat": seats,
                "curingQuality": curing_quality,
                "operateFlag": "9",
                "licenseType": "02",
                "licenseTypeChinese": "小型汽车号牌",
            },
            "fromId": self.from_id,
            "tplatformId": self.tplatform_id,
            "areaInfoVo": area_info,
            "carOwnerVo": owner,
            "premiumTrialFlag": "0",
            "tplatLoginKey": self.tplat_login_key,
        }
        if not seats:
            first_query_body["carInfoVo"].pop("selectedSeat", None)
        first_data = self._initial_model_data(first_query_body, basic_page)
        initial_models = first_data.get("carModel") or []
        initial_model = self._choose_model(initial_models, selected_model_code, "INITIAL")
        had_ocr_seats = bool(seats)
        seats = self._resolve_seats(seats, first_data, initial_model)
        ocr_result["seat_count"] = seats
        if ocr_callback and not had_ocr_seats:
            ocr_callback(copy.deepcopy(ocr_result))

        second_car_info = {
            "isQueryCarByOCR": self._vehicle_query_mode(),
            "operateFlag": "4",
            "carCheckVo": {"checkCode": "", "pmQueryNo": "", "checkFlag": 0},
            "fuelType": str(initial_model.get("fuelType") or "0"),
            "carType": "A",
            "carModel": [initial_model],
            "useNatureCodeCode": "8A",
            "modelName": initial_model.get("modelName") or driving.get("brandModel", ""),
            "licenseNo": license_no,
            "vinNo": vin,
            "engineNo": driving.get("engineNo", ""),
            "enrollDate": enroll_date,
            "billDate": "",
            "billNo": "",
            **transfer_fields,
            "specialCarProposalFlag": "",
            "colorCode": self._actual_color_code(driving, first_data),
            "selectedSeat": seats,
            "licenseType": "02",
            "licenseTypeChinese": "小型汽车号牌",
            "carOwnerNature": "1",
            "exhaustScale": str(initial_model.get("displacement") or "0").replace(".0", ""),
            "seatFlag": 0,
        }
        if getattr(self, "consistency_policy", None) == "TK_OCR_CONSISTENCY_V5":
            if curing_quality not in (None, ""):
                second_car_info["curingQuality"] = curing_quality
            if driving.get("curbWeight") not in (None, ""):
                second_car_info["authorizedDeadWeight"] = self._numeric_text(driving["curbWeight"], "")
        second_body = {
            "orderID": self.order_id,
            "channelCode": self.CHANNEL,
            "carInfoVo": second_car_info,
            "carOwnerVo": {**owner, "carOwnerNature": "1", "certificateType": "01"},
            "tplatformId": self.tplatform_id,
            "fromId": self.from_id,
            "areaInfoVo": area_info,
            "tplatLoginKey": self.tplat_login_key,
        }
        second_raw = self._post("/rest/car/modelinfo/query", second_body, referer=basic_page)
        second = self.decrypt_business_data(second_raw.get("data", ""))
        self._require_success(second, "车型精确查询")
        candidates = (second.get("data") or {}).get("carModel") or []
        selected_model = self._choose_model(candidates, selected_model_code, "EXACT")
        if getattr(self, "supplier_ocr_success_policy", None) == "SUPPLIER_OCR_SUCCESS_V1" and not seats:
            seats = self._resolve_seats(seats, second.get("data") or {}, selected_model)
            ocr_result["seat_count"] = seats
            if seats:
                second_car_info["selectedSeat"] = seats
            else:
                second_car_info.pop("selectedSeat", None)

        final_car_info = copy.deepcopy(second_car_info)
        if final_car_info["colorCode"] == "999":
            final_car_info["colorCode"] = self._actual_color_code(driving, second.get("data") or {})
        final_car_info.update(
            {
                "tonnageFlag": str(first_data.get("tonnageFlag") or "0"),
                "carModel": [selected_model],
                "modelName": selected_model.get("modelName") or final_car_info["modelName"],
                "brandName": selected_model.get("modelName") or final_car_info["modelName"],
                "fuelType": str(selected_model.get("fuelType") or final_car_info["fuelType"]),
                "exhaustScale": str(selected_model.get("displacement") or "0").replace(".0", ""),
            }
        )
        final_car_info.pop("isQueryCarByOCR", None)
        final_car_info.pop("operateFlag", None)
        final_car_info.pop("carCheckVo", None)

        check = self._post(
            "/rest/car/modelinfo/checkVehicleType",
            {
                "carInfoVo": final_car_info,
                "channelCode": self.CHANNEL,
                "orderId": self.order_id,
            },
            referer=basic_page,
        )
        self._require_success(check, "交管车辆类型校验")

        birth, sex = self._id_birth_and_sex(owner_id)
        purchase_price = str(selected_model.get("replacementValue") or "0").replace(".0", "")
        save_car_info = copy.deepcopy(final_car_info)
        save_car_info["purchasePrice"] = purchase_price
        self.logger("保存车辆、车主和地区信息")
        save_basic = self._post(
            "/rest/save/basicInfo",
            {
                "channelCode": self.CHANNEL,
                "orderID": self.order_id,
                "preFilledLastPolicyFlag": (
                    self.quote_context.get("prefilledLastPolicyFlag", "")
                    if getattr(self, "consistency_policy", None) == "TK_OCR_CONSISTENCY_V5"
                    else ""
                ),
                "isJgFlag": "",
                "carInfoVo": save_car_info,
                "carOwnerVo": {
                    "carOwnerNature": "1",
                    "birthDate": birth,
                    "name": ocr_result["name"],
                    "id": owner_id,
                    "certificateType": "01",
                    "serialno": "0",
                    "sex": sex,
                    "insuredAddress": "",
                },
                "otherInfo": {
                    "isQueryVehicleFlag": self._query_vehicle_flag(),
                    "showEngineNoFlag": "0",
                    "jyQueryFlag": False,
                    "ocrFlag": self._quote_ocr_flag(),
                    "newCarFlag": "0",
                    "kindLimitCode": "",
                    "retrospectId": self.retrospect_id,
                },
                "insureInfo": {"appliInfo": {}, "contacts": {}, "insuredInfo": {}},
                "carTaxVo": {"isPayTax": "1"},
                "tplatformId": self.tplatform_id,
                "authFailContinueFlag": "",
                "fromId": self.from_id,
                "areaInfoVo": area_info,
                "tplatLoginKey": self.tplat_login_key,
            },
            referer=basic_page,
        )
        self._require_success(save_basic, "保存车辆基础信息")

        quote_page = "https://car.tk.cn/offweb/views/page/quoteInfo/quoteInfo.html"
        self._identity(
            {"channelCode": self.CHANNEL, "userName": self.tplatform_id},
            referer=quote_page,
        )
        self.logger("初始化险种方案")
        init_quote = self._post(
            "/rest/init/quote",
            {
                "channelCode": self.CHANNEL,
                "orderID": self.order_id,
                "tplatformId": self.tplatform_id,
                "tplatLoginKey": self.tplat_login_key,
            },
            referer=quote_page,
        )
        self._validate_quote_entry(init_quote)

        precise_init = self._post(
            "/rest/precise/init",
            {
                "channelCode": self.CHANNEL,
                "orderID": self.order_id,
                "initFlag": "init",
                "tplatformId": self.tplatform_id,
                "tplatLoginKey": self.tplat_login_key,
            },
            referer=quote_page,
        )
        plan = self._decode_precise_response(precise_init, "加载默认险种")

        self.quote_context = {
            "catalog": copy.deepcopy(plan),
            "tax": {},
            "ocr": copy.deepcopy(ocr_result),
            "carInfoVo": copy.deepcopy(save_car_info),
            "id_card": copy.deepcopy(id_card),
            "birth": birth,
            "sex": sex,
        }
        plan = self._resolve_initialized_quote(plan)
        self.quote_context["catalog"] = copy.deepcopy(plan)
        self._validate_initialized_quote(plan)

        tax = self._post(
            "/rest/agent/tax",
            {
                "orderID": self.order_id,
                "tplatformId": self.tplatform_id,
                "channelCode": self.CHANNEL,
            },
            referer=quote_page,
        )
        self._require_success(tax, "读取车船税信息")
        tax_data = tax.get("data") or {}

        self.quote_context["tax"] = copy.deepcopy(tax_data)
        return copy.deepcopy(self.quote_context)

    def _validated_ocr_fields(self, driving, id_card):
        return driving, id_card

    def _ocr_seats(self, driving):
        return self._numeric_text(driving.get("loadNumber"), "5")

    def _resolve_seats(self, seats, supplier, selected_model=None):
        return seats

    def _confirmed_registration_date(self, value):
        return value

    def _transfer_car_fields(self):
        # Retired/frozen protocols retain their original request shape.
        return {"chgOwnerFlag": "0", "transferDate": ""}

    def _validate_quote_entry(self, response):
        if str(response.get("status", "1")) != "1":
            self.logger(f"险种初始化提示：{self._message(response)}")

    def _resolve_initialized_quote(self, plan):
        return plan

    def _validate_initialized_quote(self, plan):
        """Legacy quote-only behavior is preserved; staged client validates the result."""

    def _validate_calculated_tax(self, response):
        """Legacy quote-only behavior is preserved; staged client checks supplier failures."""

    def _decode_precise_response(self, response, stage):
        self._require_success(response, stage)
        return self.decrypt_business_data(response.get("data", ""))

    def calculate_prepared_quote(self, selected_plan=None, *, validate_calculated=None, car_tax_info=None):
        if not self.order_id or not self.quote_context.get("catalog"):
            raise TkApiError("请先准备当前订单的险种资料")
        quote_page = "https://car.tk.cn/offweb/views/page/quoteInfo/quoteInfo.html"
        plan = selected_plan if selected_plan is not None else self.quote_context["catalog"]
        tax_data = self.quote_context["tax"]
        self.logger("提交默认险种方案并计算保费")
        quote_payload = copy.deepcopy(plan)
        quote_payload.update(
            {
                "chargingPost": [],
                "riskType": "0808",
                "initFlag": "quote",
                "orderID": self.order_id,
                "carTaxInfo": copy.deepcopy(car_tax_info)
                if car_tax_info is not None
                else {"taxFlag": tax_data.get("taxFlag") or "T"},
                "tplatformId": self.tplatform_id,
                "tplatLoginKey": self.tplat_login_key,
            }
        )
        progress = getattr(self, "_quote_progress", None)
        if isinstance(progress, dict) and isinstance(progress.get("calculated"), dict):
            calculated_plan = copy.deepcopy(progress["calculated"])
            if validate_calculated is not None:
                validate_calculated(calculated_plan)
        else:
            if isinstance(progress, dict):
                progress["writeOutcome"] = "IN_FLIGHT"
            calculated = self._post("/rest/precise/init", quote_payload, referer=quote_page)
            calculated_plan = self._decode_precise_response(calculated, "计算保费")
            if validate_calculated is not None:
                validate_calculated(calculated_plan)
            if isinstance(progress, dict):
                progress["calculated"] = copy.deepcopy(calculated_plan)
                progress["writeOutcome"] = "CONFIRMED"

        tax_response = self._post(
            "/rest/agent/tax",
            {
                "orderID": self.order_id,
                "tplatformId": self.tplatform_id,
                "channelCode": self.CHANNEL,
            },
            referer=quote_page,
        )
        self._validate_calculated_tax(tax_response)
        quotation_raw = self._post(
            "/rest/init/quotation",
            {"orderID": self.order_id, "channelCode": self.CHANNEL, "initFlag": "1"},
            referer=quote_page,
        )
        quotation = self.decrypt_business_data(quotation_raw.get("data", ""))
        self._require_success(quotation, "读取报价结果")
        result = quotation.get("data") or {}
        result["orderID"] = self.order_id
        self.quote_context["calculatedPlan"] = copy.deepcopy(calculated_plan)
        self.quote_context["businessScore"] = calculated_plan.get("businessScore")
        self.quote_result = copy.deepcopy(result)
        self.logger("接口报价完成")
        return result
