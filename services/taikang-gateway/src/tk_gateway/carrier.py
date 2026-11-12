"""Translate confirmed app fields to the supplied, captured Taikang protocol.

No enterprise-WeChat objects, old platform IDs, proposal submission or payment.
The original protocol modules are vendored unchanged and recorded by SHA256.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
import threading
import time
from taikang_executor.client import TkApiError, TkModelAmbiguous, TkTransportError, choose_model
from taikang_executor.coverage_mapping import CoverageMappingError
from taikang_executor.staged_client import (
    StagedTkClient, TkManualReview, TkOutcomeUnknown, TkSessionExpired,
    TkSupplierRejected, TkVerificationRequired,
)
from taikang_executor import stage_results
from .config import Settings
from .models import QuoteRequest


def unavailable(message: str, status: str = "MANUAL_REQUIRED"):
    return {"status": status, "insurer": "TAIKANG", "demo": False, "message": message}


class QuoteOnlyClient(StagedTkClient):
    """Enforce the smaller new system's scope at the outbound boundary too."""
    def __init__(self):
        super().__init__()
        self.request_timeout = (8, 30)
        self.deadline = time.monotonic() + 150
        self.request_guard = self.check_deadline
        self.login_verified = False

    def check_deadline(self):
        if time.monotonic() > self.deadline:
            raise TkOutcomeUnknown("报价调用期限已到，请人工核实原笔")

    def _choose_model(self, candidates, selected_model_code=None, stage=None):
        # Never silently choose the first of several supplier vehicle models.
        return choose_model(candidates, selected_model_code, stage)

    def _post(self, path, body, **kwargs):
        if (path.startswith("/rest/pay/") or path.startswith("/carCheck/")
                or "proposal" in path.lower() or "/management/" in path):
            raise TkApiError("当前独立系统仅执行报价，不调用保司投保或支付接口")
        value = super()._post(path, body, **kwargs)
        if path == "/rest/tplatform/login":
            data = value.get("data") if isinstance(value, dict) else None
            if not isinstance(data, dict) or str(data.get("loginStatus")) != "0":
                raise TkVerificationRequired("泰康账号需要人工核对登录状态或完成验证")
            self.login_verified = True
        return value

    def login(self, username, password):
        self.login_verified = False
        result = super().login(username, password)
        if not self.login_verified or not self.from_id or not self.com_code:
            raise TkVerificationRequired("未确认当前泰康账号正常登录")
        # Some responses carry the login name; validate it whenever present.
        identity = self.user_info.get("userName") or self.user_info.get("username")
        if identity and str(identity).strip() != username.strip():
            raise TkVerificationRequired("登录返回的账号身份不一致")
        return result


def confirmed_plan(request: QuoteRequest):
    compulsory = request.plan == "COMPULSORY"
    return {
        "mode": {"STANDARD": "THIRD_PARTY", "FULL": "FULL", "COMPULSORY": "COMPULSORY"}[request.plan],
        "vehicleLoss": request.plan == "FULL",
        "thirdParty": "0" if compulsory else request.thirdPartyAmount,
        "driver": "0" if compulsory else request.driverAmount,
        "passengerPerSeat": "0" if compulsory else request.passengerAmount,
        "medicalThirdParty": "0" if compulsory else request.medicalAmount,
        "medicalDriver": "0", "medicalPassengerPerSeat": "0",
        # The request asks for car insurance only. Do not sell the old bundle's
        # accident products or invent commissions / price tiers.
        "nonCarIncluded": False, "nonCarPlanCode": None, "nonCarPolicyVersion": 2,
    }


def validation_problem(request: QuoteRequest):
    if request.vehicle.vehicleType and request.vehicle.vehicleType != request.vehicleType:
        return "车辆分类与已确认资料不一致，请人工核对车辆类型。"
    if request.vehicleType == "MOTORCYCLE":
        return "摩托车由人工客服处理，未调用泰康自动报价。"
    if request.vehicleType == "TRUCK":
        return "现有泰康协议固定为家用车用途，货车用途及吨位字段需核实，已转人工。"
    v = request.vehicle
    if v.useNature not in {"家庭自用", "家用", "家庭自用汽车"}:
        return "当前自动报价仅支持已核实的家庭自用车辆，其他使用性质请人工处理。"
    required = (v.plateNo, v.vin, v.engineNo, v.brandModel, v.registerDate,
                v.issueDate, v.ownerName, v.idNumber, v.address)
    if not all(required) or v.seatCount < 1:
        return "请补全车主姓名、身份证、证件地址、车牌、VIN、发动机号、车型、初登/发证日期和座位数。"
    if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", v.vin.upper()):
        return "请核对17位车辆识别代号。"
    if not re.fullmatch(r"\d{17}[0-9Xx]", v.idNumber):
        return "自动报价目前仅支持18位居民身份证，其他证件请人工处理。"
    if request.plan != "COMPULSORY" and Decimal(request.medicalAmount) > 0 and Decimal(request.thirdPartyAmount) == 0:
        return "选择医保外三者责任时需要同时选择第三者责任险。"
    return None


class Carrier:
    def __init__(self, settings: Settings, client_factory=QuoteOnlyClient):
        self.settings = settings
        self.client_factory = client_factory
        self.lock = threading.Lock()

    def login_check(self):
        try:
            self.settings.validate_carrier()
        except ValueError as error:
            return {"status": "ERROR", "message": str(error)}
        if not self.lock.acquire(timeout=1):
            return {"status": "ERROR", "message": "当前泰康账号正在处理报价，请稍后再检查。"}
        client = None
        try:
            client = self.client_factory()
            client.login(self.settings.username, self.settings.password)
            return {"status": "ONLINE", "message": "已确认当前账号正常登录；此次检查未创建报价订单。"}
        except TkVerificationRequired:
            return {"status": "VERIFICATION_REQUIRED", "message": "请在泰康官方页面完成账号验证后重新检查。"}
        except Exception:
            return {"status": "ERROR", "message": "泰康登录未确认成功，请核对账号配置及网络。"}
        finally:
            try:
                if client is not None:
                    client.session.close()
            except Exception:
                # Transport cleanup must not replace an already confirmed result.
                pass
            finally:
                self.lock.release()

    def quote(self, request: QuoteRequest):
        issue = validation_problem(request)
        if issue:
            return unavailable(issue), {}
        try:
            self.settings.validate_carrier()
        except ValueError as error:
            return unavailable(str(error)), {}
        if not self.lock.acquire(timeout=1):
            return unavailable("泰康账号正在处理另一笔报价，请客服稍后发起新请求；本次未建单。"), {}
        client = None
        order_creation_started = False
        try:
            client = self.client_factory()
            client.apply_business_settings(self.settings.business_settings())
            client.login(self.settings.username, self.settings.password)
            # The independent app requires fully confirmed fields. Do not use
            # the old WeCom reply parser or guess values from prior sessions.
            v = request.vehicle
            fields = {
                "name": v.ownerName, "idNumber": v.idNumber.upper(), "licenseNo": v.plateNo.upper(),
                "vin": v.vin.upper(), "engineNo": v.engineNo, "modelName": v.brandModel,
                "registrationDate": v.registerDate, "issueDate": v.issueDate,
                "certificateAddress": v.address, "seatCount": str(v.seatCount),
            }
            order_creation_started = True
            client.prepare_order()
            client.prepare_quote({"textFields": fields}, selected_model_code=v.selectedModelCode)
            plan = confirmed_plan(request)
            result = client.calculate_coverage(plan, v.seatCount)
            normalized = stage_results.quoted(client, {
                "tenantId": "mini-program", "accountId": "dedicated-taikang-account",
                "credentialVersion": 1, "coverage": plan, "prepared": {"seatCount": v.seatCount},
            }, result)
            amounts = normalized["amounts"]
            # Show actual amounts for each row from the current supplier quote;
            # never attach the request's limit to a different returned risk.
            quote_rows = result["quotation"].get("orderInfoVoCI", {}).get("allKinds", [])
            limits = {str(row.get("kindCName")): str(row.get("amount") or row.get("quoteAmount") or "")
                      for row in quote_rows if isinstance(row, dict)}
            coverages = [{"name": name, "premium": premium, "amount": limits.get(name, "")}
                         for name, premium in amounts.items() if name != "商业险"]
            response = {
                "status": "QUOTED", "insurer": "TAIKANG", "plan": request.plan, "demo": False,
                "totalPremium": normalized["totalPremium"],
                "compulsoryPremium": amounts["交强险"], "vehicleTax": amounts["车船税"],
                "commercialPremium": amounts.get("商业险", "0.00"), "coverages": coverages,
                "supplierQuoteRef": normalized["quotationRef"],
                "supplierOrderId": client.order_id,
                "validUntil": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
                "message": "泰康当前报价已返回，金额以实际核保为准。确认后提交平台人工投保申请。",
            }
            return response, {"orderId": client.order_id, "context": normalized["context"]}
        except TkModelAmbiguous as error:
            return unavailable("保司返回多个车型，请客服核对并确认具体车型。"), self.evidence(client, {
                "modelCandidates": error.candidates, "modelStage": error.stage,
            })
        except TkVerificationRequired:
            return unavailable("泰康账号需要额外验证，请管理员在官方页面完成验证。"), self.evidence(client)
        except (TkManualReview, CoverageMappingError, TkSupplierRejected):
            return unavailable("本笔车型、税务或险种反馈需要人工核对，未生成可确认的报价。"), self.evidence(client)
        except (TkOutcomeUnknown, TkTransportError, TkSessionExpired):
            return unavailable("本笔保司结果未确认，请客服核查原笔，系统未自动重报。",
                               "OUTCOME_UNKNOWN" if order_creation_started else "FAILED"), self.evidence(client)
        except Exception:
            return unavailable("泰康请求未完成，请客服核查配置及原笔记录。",
                               "OUTCOME_UNKNOWN" if order_creation_started else "FAILED"), self.evidence(client)
        finally:
            try:
                if client is not None:
                    client.session.close()
            except Exception:
                pass
            finally:
                self.lock.release()

    @staticmethod
    def evidence(client, extra=None):
        if client is None:
            return extra or {}
        # This is encrypted inside the ledger, not returned through the public API.
        try:
            snapshot = client.export_order_context()
        except Exception:
            snapshot = {"orderId": getattr(client, "order_id", "")}
        return {"orderContext": snapshot, **(extra or {})}
