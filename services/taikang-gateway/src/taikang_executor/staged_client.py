"""Captured TK stages. Java must authorize, persist and lease each command.

This adapter is not wired to the legacy worker and does not start a business
flow, choose an account, retry an uncertain proposal, or decide policy issuance.
Continuation dictionaries contain sensitive data: send through the protected
internal contract for encryption, never log or save them as plaintext files.
"""

import copy
import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
from datetime import datetime
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

import requests

from taikang_executor.ocr_transport import OcrTimingAdapter, observe_ocr
from taikang_executor.ocr_review import review_fields
from taikang_executor.client import TkApiClient, TkApiError, TkSessionExpired, choose_model
from taikang_executor.coverage_mapping import (
    CoverageMappingError,
    map_coverage,
    money_yuan,
    validate_calculated_selection,
)
from taikang_executor.quote_paths import ALLOWED_PATHS


class TkManualReview(TkApiError):
    def __init__(self, message, supplier_feedback=None):
        super().__init__(message)
        if supplier_feedback:
            self.supplier_feedback = supplier_feedback


def business_feedback(stage, payload):
    reasons = []
    origins = []
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    containers = (("", payload), ("data.", data), ("other.", payload.get("other")), ("data.other.", data.get("other")))
    for prefix, container in containers:
        if not isinstance(container, dict):
            continue
        for key in (
            "message",
            "msg",
            "checkReason",
            "underwriteReason",
            "ruleMessage",
            "spResMsg",
            "notice",
            "messageBZ",
            "messageSY",
        ):
            value = container.get(key)
            values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
            for item in values:
                if isinstance(item, str) and item.strip():
                    if item not in reasons:
                        reasons.append(item)
                    origin = {
                        "reasonIndex": reasons.index(item),
                        "field": prefix + key,
                        "scope": {"messageBZ": "COMPULSORY", "messageSY": "COMMERCIAL"}.get(key, "GENERAL"),
                    }
                    if origin not in origins:
                        origins.append(origin)
    result = {"stage": stage, "reason": reasons[0], "reasons": reasons} if reasons else {"stage": stage}
    if origins:
        result["reasonOrigins"] = origins
    # Preserve only bounded protocol codes, never arbitrary nested response data.
    for key in ("status", "messageCode"):
        value = payload.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 999_999_999:
            result[key] = value
        elif isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", value):
            result[key] = value
    return result


class TkOutcomeUnknown(TkApiError):
    pass


class TkVerificationRequired(TkApiError):
    pass


class TkOcrReviewRequired(TkManualReview):
    pass


class TkFieldRecoveryRequired(TkOcrReviewRequired):
    def __init__(self, documents):
        super().__init__("本笔字段证据恢复中")
        self.documents = documents


class TkNameReviewRequired(TkOcrReviewRequired):
    def __init__(self, evidence):
        super().__init__("姓名专项复核中")
        self.identity_evidence = evidence


class TkSupplierRejected(TkApiError):
    """Supplier text goes only to the protected encrypted receipt, never exception logs."""

    def __init__(self, stage, payload):
        super().__init__(stage + "未返回明确成功状态")
        self.supplier_feedback = business_feedback(stage, payload)


class StagedTkClient(TkApiClient):
    DEFAULT_PROVINCE = {"name": "云南省", "code": "530000"}
    DEFAULT_CITY = {"name": "曲靖市", "code": "530300"}
    EXTRA_PATHS = frozenset(
        {
            "/rest/controller/entrance",
            "/rest/save/quote",
            "/rest/init/proposal",
            "/rest/pay/forward",
            "/rest/order/management/agent/completeAgent",
            "/rest/order/management/agent/paymentAgent",
            "/rest/order/management/agent/pendingAgent",
            "/carCheck/qualityVerifyImg",
            "/carCheck/AIResult/query",
            "/carCheck/submit",
            "/carCheck/qualityCheck/userAction",
        }
    )
    ACTIONS = frozenset({"000051", "000012", "000038", "000021", "000052", "000133"})

    def __init__(self):
        super().__init__()
        self.consistency_policy = None
        self.field_recovery = {}
        self._field_recovered = False
        self.strict_document_fields = True
        self.supplier_ocr_success_policy = None
        self.ocr_review_enabled = False
        self.transfer_policy = None
        self.text_policy = None
        self.text_lookup_receipt = None
        self.confirmed_text_edits = {}
        self.transfer_decision = None
        self.transfer_decision_resolver = None
        self.transfer_adoption_resolver = None
        self.quote_business_date = None
        self.prepare_mode = None
        self.identity_anchor = None
        self.ocr_overrides = {}
        self.request_guard = lambda: None
        # Authentication identifiers must come from this account's real login.
        self.from_id = ""
        self.com_code = ""
        self._proposal_started = False
        self.proposal_status2_policy = None
        self._precise_response_states = []
        self._proposal_confirmation = {}
        self.proposal_result = {}
        self.payment_context = {}
        self.underwriting_result = {}
        self.inspection_context = {}
        self.ocr_image_diagnostics = []
        self.ocr_document_facts = {}
        self.post_proposal_enabled = False
        self._page_default_models = {}
        self.insured_area = {
            "provinceCode": "530000",
            "provinceName": "云南省",
            "cityCode": "530300",
            "cityName": "曲靖市",
        }

    def apply_business_settings(self, settings):
        """Translate the Java-frozen configuration; never read mutable tenant settings here."""
        if settings is None:
            return
        if not isinstance(settings, dict):
            raise TkApiError("冻结业务配置格式不正确")
        for key in ("quoteArea", "insuredArea"):
            area = settings.get(key)
            if not isinstance(area, dict) or any(
                not isinstance(area.get(field), str) or not area[field].strip()
                for field in ("provinceCode", "provinceName", "cityCode", "cityName")
            ):
                raise TkApiError("冻结地区配置缺少实际代码和名称")
            if any(len(area[field]) != 6 or not area[field].isdigit() for field in ("provinceCode", "cityCode")):
                raise TkApiError("冻结地区代码格式不正确")
        quote_area = settings["quoteArea"]
        self.DEFAULT_PROVINCE = {"name": quote_area["provinceName"], "code": quote_area["provinceCode"]}
        self.DEFAULT_CITY = {"name": quote_area["cityName"], "code": quote_area["cityCode"]}
        self.insured_area = copy.deepcopy(settings["insuredArea"])

    def _choose_model(self, candidates, selected_model_code=None, stage=None):
        explicit = selected_model_code.get(stage) if isinstance(selected_model_code, dict) else selected_model_code
        from .vehicle_lookup import prefill_active, choose

        if prefill_active(self):
            return choose(self, candidates, explicit, stage)
        if explicit:
            return choose_model(candidates, explicit, stage)
        if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
            raise TkManualReview("泰康默认车型候选缺失或格式不正确")
        model = candidates[0]
        if not isinstance(model.get("modelCode"), str) or not model["modelCode"].strip():
            raise TkManualReview("泰康默认车型缺少真实车型代码")
        self._page_default_models[stage] = {
            "modelCode": model["modelCode"],
            "candidateCount": len(candidates),
            "selectionSource": "SUPPLIER_PAGE_DEFAULT_FIRST",
        }
        return model

    def _attach_response_diagnostic(self, error):
        facts = getattr(self, "last_http_diagnostic", None)
        if isinstance(facts, dict) and facts.get("path") == getattr(self, "last_supplier_step", None):
            error.transport_diagnostic = copy.deepcopy(facts)
        return error

    def _require_success(self, payload, stage):
        try:
            self._check_expired(payload)
        except TkSessionExpired as error:
            raise self._attach_response_diagnostic(error)
        if not isinstance(payload, dict) or str(payload.get("status")) != "1":
            # Do not include an uncontrolled supplier response (possibly PII).
            raise self._attach_response_diagnostic(
                TkSupplierRejected(stage, payload if isinstance(payload, dict) else {})
            )
        return payload

    @staticmethod
    def _check_expired(payload):
        # Exact supplier message observed on 2026-10-15. Do not infer expiry
        # from arbitrary business text, 403, missing data or network failures.
        if isinstance(payload, dict) and str(payload.get("status")) != "1":
            for key in ("message", "msg"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip().rstrip("!！。") == "您的登录状态已过期，请重新登录":
                    error = TkSessionExpired()
                    error.supplier_feedback = business_feedback("登录会话", payload)
                    raise error

    def _post(self, path, body, *, referer, xhr=True, action_type=None):
        from .preparation_reuse import post

        return post(self, self._post_uncached, path, body, referer=referer, xhr=xhr, action_type=action_type)

    def _post_uncached(self, path, body, *, referer, xhr=True, action_type=None):
        self.last_supplier_step = path
        if path != "/rest/controller/identity":
            self.business_write_started = True
        self.request_guard()
        if path not in ALLOWED_PATHS | self.EXTRA_PATHS:
            raise TkApiError("未验证的泰康接口")
        if action_type not in {None, "queryClaimData"} | self.ACTIONS:
            raise TkApiError("未验证的泰康动作")
        if action_type in self.ACTIONS and path != "/rest/controller/entrance":
            raise TkApiError("动作与接口不匹配")
        if path == "/rest/controller/entrance" and action_type not in self.ACTIONS:
            raise TkApiError("入口接口需要已验证动作")
        response = super()._post(path, body, referer=referer, xhr=xhr, action_type=action_type)
        try:
            self._check_expired(response)
        except TkSessionExpired as error:
            raise self._attach_response_diagnostic(error)
        if path == "/rest/tplatform/login":
            self._require_success(response, "登录")
            data = response.get("data")
            if not isinstance(data, dict):
                raise TkApiError("登录响应格式错误")
            state = str(data.get("loginStatus", ""))
            if state in {"1", "2", "3"}:
                raise TkVerificationRequired("登录需要人工验证或解除验证限制")
            if state != "0" or any(not data.get(key) for key in ("tplatformId", "tplatLoginKey", "carssToken")):
                raise TkApiError("登录响应缺少明确登录状态或当前会话凭证")
        return response

    def decode_success(self, payload, stage):
        """Recognize both captured response envelopes without assuming success."""
        if not isinstance(payload, dict):
            raise TkApiError(stage + "响应格式错误")
        outer_success = "status" in payload
        if outer_success:
            self._require_success(payload, stage)
        decoded = self.decrypt_business_data(payload.get("data"))
        if not isinstance(decoded, dict):
            raise TkApiError(stage + "业务响应格式错误")
        if "status" in decoded:
            self._require_success(decoded, stage)
            result = decoded.get("data")
            if not isinstance(result, dict):
                raise TkApiError(stage + "缺少业务数据")
            return result
        if not outer_success:
            raise TkApiError(stage + "没有明确成功状态")
        return decoded

    def _decode_precise_response(self, payload, stage):
        """Only the captured ordinary precise/init envelope accepts 4/10.

        Caller-specific initialization/quote_success/selection checks still run;
        these transport statuses never establish a successful business quote.
        """
        self._check_expired(payload)
        if not isinstance(payload, dict) or str(payload.get("status")) not in {"1", "4", "10"}:
            raise TkSupplierRejected(stage, payload if isinstance(payload, dict) else {})
        decoded = self.decrypt_business_data(payload.get("data"))
        if not isinstance(decoded, dict):
            raise TkApiError(stage + "业务响应格式错误")
        if "status" in decoded:
            self._require_success(decoded, stage)
            decoded = decoded.get("data")
            if not isinstance(decoded, dict):
                raise TkApiError(stage + "缺少业务数据")
        self._precise_response_states.append({"stage": stage, "outerStatus": str(payload["status"])})
        return decoded

    def login(self, username, password):
        # User-authorized password-only test path. Captcha implementation is
        # retained in the legacy client, but is NOT a fallback for staged login.
        result = super().login(username, password, use_captcha=False)
        if not self.from_id or not self.com_code:
            raise TkApiError("登录响应缺少当前账号身份，不能沿用抓包账号的标识")
        return result

    def prepare_order(self):
        result = super().prepare_order()
        self.initialize_quote_entry()
        return result

    def initialize_quote_entry(self):
        if not self.order_id:
            raise TkApiError("需要本笔真实外部订单")
        response = self._post(
            "/rest/controller/entrance",
            {
                "channelCode": self.CHANNEL,
                "fromID": self.from_id,
                "tplatformId": self.tplatform_id,
            },
            referer="https://car.tk.cn/offweb/views/page/areaInfo/areaInfo.html",
            action_type="000051",
        )
        self._require_success(response, "初始化报价入口")

    def _initialize_basic_page(self):
        if getattr(self, "evidence_policy", None) == "PRIVATE_OCR_EVIDENCE_V1" and self.quote_context.get(
            "basicPageInitialized"
        ):
            page = f"https://car.tk.cn/offweb/views/page/basicInfo/basicInfo.html?fromId={self.from_id}"
            self._identity({"channelCode": self.CHANNEL, "orderId": self.order_id}, referer=page)
            self._basic_page_initialized = True
            return page
        page = super()._initialize_basic_page()
        if getattr(self, "evidence_policy", None) == "PRIVATE_OCR_EVIDENCE_V1":
            self.quote_context["basicPageInitialized"] = True
            self._basic_page_initialized = True
        return page

    def prepare_quote(self, documents, ocr_callback=None, selected_model_code=None):
        self._preparing = True
        self._prepare_request_cache = copy.deepcopy(self.quote_context.get("prepareRequestCache") or {})
        self._basic_page_initialized = self.quote_context.get("basicPageInitialized") is True
        self._prepare_vehicle_hash = self.quote_context.get("prepareVehicleHash", "")
        self._prepare_ocr_prefill_hash = self.quote_context.get("prepareOcrPrefillHash", "")
        self._prepare_write_unknown = self.quote_context.get("prepareWriteUnknown")
        try:
            return self._prepare_quote_inner(documents, ocr_callback, selected_model_code)
        finally:
            if getattr(self, "evidence_policy", None) == "PRIVATE_OCR_EVIDENCE_V1":
                self.quote_context["basicPageInitialized"] = self._basic_page_initialized
                self.quote_context["prepareVehicleHash"] = self._prepare_vehicle_hash
                self.quote_context["prepareOcrPrefillHash"] = self._prepare_ocr_prefill_hash
                self.quote_context["prepareWriteUnknown"] = self._prepare_write_unknown
                self.quote_context["prepareRequestCache"] = self._prepare_request_cache
            self._preparing = False

    def _prepare_quote_inner(self, documents, ocr_callback=None, selected_model_code=None):
        if self._proposal_started:
            raise TkManualReview("投保已提交，不能覆盖当前身份或车辆资料")
        self._page_default_models = {}
        self.ocr_review_snapshot = {}
        if "textFields" in documents:
            return self._prepare_text_quote(documents["textFields"], selected_model_code)
        if "images" not in documents:
            result = super().prepare_quote(documents, ocr_callback, selected_model_code)
            self.quote_context["pageDefaultModels"] = copy.deepcopy(self._page_default_models)
            return result

        images = documents["images"]
        if not isinstance(images, list) or not 1 <= len(images) <= (
            6
            if getattr(self, "identity_policy", None) in {"OWNER_INSURED_APPLICANT_V1", "OWNER_INSURED_APPLICANT_V2"}
            else 4
        ):
            raise TkApiError("需要本笔身份证和行驶证原图，支持合拍")
        self._physical_images = list(dict.fromkeys(images))
        resume = self.quote_context.get("ocrWorkingDraft") or self.quote_context.get("ocrDraft")
        if getattr(self, "consistency_policy", None) == "TK_OCR_CONSISTENCY_V5" and self.field_recovery:
            resume = None
        self._ocr_pages = copy.deepcopy(resume) if self.ocr_review_enabled and isinstance(resume, dict) else None
        self._raw_ocr_draft = copy.deepcopy(self.quote_context.get("ocrDraft"))
        self._raw_ocr_responses = copy.deepcopy(self.quote_context.get("ocrOriginalResponses") or [])
        self._ocr_field_alternatives = copy.deepcopy(self.quote_context.get("ocrFieldAlternatives") or [])
        try:
            # The captured smartOcr request has no page-specific endpoint: all
            # physical originals use imgTypes=IdFront,Vehiclelicense,Subvehiclelicense.
            # Parent translation consumes verified roles, never repeats uploads.
            result = super().prepare_quote(
                {role: images[0] for role in ("vehicle_front", "vehicle_back", "id_front")},
                ocr_callback,
                selected_model_code,
            )
            self.quote_context["pageDefaultModels"] = copy.deepcopy(self._page_default_models)
            self._persist_ocr_draft()
            return result
        finally:
            del self._physical_images
            self._ocr_pages = None

    def _prepare_text_quote(self, fields, selected_model_code):
        if getattr(self, "text_policy", None) in {"FLEXIBLE_TEXT_V1", "FLEXIBLE_TEXT_V2", "FLEXIBLE_TEXT_V3"}:
            from .text_preparation import prepare

            return prepare(self, fields, selected_model_code)
        if not isinstance(fields, dict):
            raise TkApiError("文字报价资料格式不正确")
        fields = copy.deepcopy(fields)
        fields.update(self.quote_context.get("textFields") or {})
        fields.update(self.ocr_overrides)
        for key in ("name", "idNumber", "licenseNo", "vin", "engineNo", "registrationDate", "modelName"):
            if not isinstance(fields.get(key), str) or not fields[key].strip():
                raise TkApiError("文字报价资料不完整")
        self.ocr_review_snapshot = {
            **fields,
            "ownerName": fields["name"],
            "idName": fields["name"],
            "seatCount": fields.get("seatCount", ""),
        }
        self._text_quote_fields = fields
        self._text_query_mode = "2"
        try:
            basic_page = self._initialize_basic_page()
            driving = {"brandModel": fields["modelName"], "engineNo": fields["engineNo"]}
            if fields.get("issueDate"):
                driving["issueDate"] = self._api_date(fields["issueDate"])
            card = {"name": fields["name"], "id": fields["idNumber"], "address": fields.get("certificateAddress", "")}
            date = self._api_date(fields["registrationDate"])
            facts = {
                "name": fields["name"],
                "id_number": fields["idNumber"],
                "license_no": fields["licenseNo"],
                "vin": fields["vin"],
                "engine_no": fields["engineNo"],
                "model_name": fields["modelName"],
                "enroll_date": date,
            }
            self._prepare_vehicle(
                driving, card, facts, fields.get("seatCount", ""), "0", date, selected_model_code, None, basic_page
            )
        finally:
            self.quote_context["inputKind"] = "TEXT"
            self.quote_context["textFields"] = copy.deepcopy(fields)
            self.quote_context["pageDefaultModels"] = copy.deepcopy(self._page_default_models)
            del self._text_quote_fields
            del self._text_query_mode
        return copy.deepcopy(self.quote_context)

    def _initial_model_data(self, body, basic_page):
        if getattr(self, "_text_lookup_result", None) is not None:
            return copy.deepcopy(self._text_lookup_result)
        fields = getattr(self, "_text_quote_fields", None)
        if getattr(self, "_field_recovered", False) and fields is None:
            from .text_preparation import lookup

            car = body["carInfoVo"]
            return lookup(
                self,
                {
                    "licenseNo": car.get("licenseNo"),
                    "vin": car.get("vinNo"),
                    "engineNo": car.get("engineNo"),
                    "registrationDate": car.get("enrollDate"),
                    "modelName": car.get("modelName"),
                },
                basic_page,
            )
        if fields is None:
            data = super()._initial_model_data(body, basic_page)
            from .vehicle_lookup import expand_prefill

            car = body.get("carInfoVo") or {}
            return expand_prefill(
                self,
                data,
                {"licenseNo": car.get("licenseNo"), "vin": car.get("vinNo"), "engineNo": car.get("engineNo")},
                basic_page,
            )
        request = {
            key: copy.deepcopy(body[key])
            for key in ("orderID", "channelCode", "fromId", "tplatformId", "areaInfoVo", "tplatLoginKey")
        }
        request["carInfoVo"] = {
            "isQueryCarByOCR": "2",
            "carType": "A",
            "licenseNo": fields["licenseNo"],
            "operateFlag": "6",
            "licenseType": "02",
            "licenseTypeChinese": "小型汽车号牌",
        }
        data = self.decode_success(self._post("/rest/car/modelinfo/query", request, referer=basic_page), "车牌车型查询")
        dto = data.get("carInfoDto") or {}
        # A supplied VIN selects the captured VIN query when plate data has not
        # established the same VIN; never adopt a different plate's vehicle.
        if dto.get("vinNo") != fields["vin"]:
            self._text_query_mode = "3"
            request["carInfoVo"] = {
                "isQueryCarByOCR": "3",
                "carType": "A",
                "enrollDate": self._api_date(fields["registrationDate"]),
                "vinNo": fields["vin"],
                "operateFlag": "3",
            }
            request["premiumTrialFlag"] = "0"
            data = self.decode_success(
                self._post("/rest/car/modelinfo/query", request, referer=basic_page), "VIN车型查询"
            )
        return data

    def _vehicle_query_mode(self):
        if getattr(self, "_field_recovered", False):
            return self._text_query_mode
        return (
            self._text_query_mode
            if getattr(self, "_text_quote_fields", None) is not None
            else super()._vehicle_query_mode()
        )

    def _quote_ocr_flag(self):
        if getattr(self, "_field_recovered", False):
            return 2
        return 2 if getattr(self, "_text_quote_fields", None) is not None else super()._quote_ocr_flag()

    def _query_vehicle_flag(self):
        if getattr(self, "_field_recovered", False):
            return True
        return (
            self._text_query_mode == "3"
            if getattr(self, "_text_quote_fields", None) is not None
            else super()._query_vehicle_flag()
        )

    def _ocr_seats(self, driving):
        value = str(driving.get("loadNumber") or "").strip()
        if not value:
            return ""
        # Match the captured official page's calcStr: whitespace is an additive
        # separator and units are removed. No eval; only the observed sum form is
        # accepted here. Raw supplier OCR remains in the immutable draft.
        expression = re.sub(r"\s+", "+", value)
        expression = re.sub(r"[^0-9+\-*/]", "", expression)
        if re.fullmatch(r"[0-9]{1,3}\.0(?:人|座)?", value):
            value = str(int(Decimal(self._numeric_text(value))))
        elif "." not in value and re.fullmatch(r"[0-9]{1,3}(?:\+[0-9]{1,3})*", expression):
            value = str(sum(int(part) for part in expression.split("+")))
        else:
            if self.supplier_ocr_success_policy == "SUPPLIER_OCR_SUCCESS_V1":
                return ""  # Preserve raw OCR, ask supplier model/catalog for actual seats.
            if self.ocr_review_enabled:
                raise TkOcrReviewRequired("证件座位数格式无效，请引用OCR消息修改载客数")
            raise TkManualReview("证件座位数格式无效，请核实原图")
        seats = self._numeric_text(value)
        if not 1 <= int(Decimal(seats)) <= 100:
            if self.supplier_ocr_success_policy == "SUPPLIER_OCR_SUCCESS_V1":
                return ""
            if self.ocr_review_enabled:
                raise TkOcrReviewRequired("证件座位数超出有效范围，请引用OCR消息修改载客数")
            raise TkManualReview("证件座位数超出有效范围，请核实原图")
        return str(int(Decimal(seats)))

    def _persist_ocr_draft(self):
        if not self.ocr_review_enabled or not hasattr(self, "_working_ocr_draft"):
            return
        if hasattr(self, "_java_identity_roles"):
            self.quote_context["identityRoles"] = copy.deepcopy(self._java_identity_roles)
        if getattr(self, "intake_policy", None) == "UNIFIED_INTAKE_V1":
            self.quote_context["inputKind"] = getattr(self, "intake_kind", None) or "IMAGES"
        self.quote_context["ocrDraft"] = copy.deepcopy(self._raw_ocr_draft)
        self.quote_context["ocrWorkingDraft"] = copy.deepcopy(self._working_ocr_draft)
        self.quote_context["ocrCorrectionAudit"] = copy.deepcopy(self._ocr_correction_audit)
        if self.supplier_ocr_success_policy == "SUPPLIER_OCR_SUCCESS_V1":
            self.quote_context["ocrPolicy"] = self.supplier_ocr_success_policy
            self.quote_context["ocrOriginalResponses"] = copy.deepcopy(getattr(self, "_raw_ocr_responses", []))
            self.quote_context["ocrFieldAlternatives"] = copy.deepcopy(getattr(self, "_ocr_field_alternatives", []))

    def _validated_ocr_fields(self, driving, id_card):
        if not self.ocr_review_enabled:
            return driving, id_card
        from taikang_executor.ocr_review import apply_ocr_review, review_fields, review_reason

        pages = {"DrivingLicense": copy.deepcopy(driving), "IdCard": copy.deepcopy(id_card)}
        if not getattr(self, "_raw_ocr_draft", None):
            self._raw_ocr_draft = (
                {"DrivingLicense": {}, "IdCard": {}}
                if getattr(self, "_field_recovered", False)
                else copy.deepcopy(pages)
            )
        if getattr(self, "_field_recovered", False):
            self.quote_context["fieldRecoveryEvidence"] = copy.deepcopy(self.field_recovery)
        supplier_ocr = self.supplier_ocr_success_policy == "SUPPLIER_OCR_SUCCESS_V1"
        if supplier_ocr:
            for page in pages.values():
                for key, value in list(page.items()):
                    if value is None:
                        page[key] = ""
                    elif isinstance(value, (int, float, bool)):
                        page[key] = str(value)
        pages, audit = apply_ocr_review(
            pages,
            self.identity_anchor,
            self.ocr_overrides,
            preserve_supplier_names=supplier_ocr,
            corrected_mass=self.consistency_policy == "TK_OCR_CONSISTENCY_V5",
            unified_fields=getattr(self, "text_policy", None) == "FLEXIBLE_TEXT_V3",
        )
        self._working_ocr_draft, self._ocr_correction_audit = pages, audit
        self._persist_ocr_draft()
        # Role confirmation can exit before the final normalization below. Its
        # exception handler still needs a complete per-order review snapshot.
        self.ocr_review_snapshot = review_fields(pages)
        if getattr(self, "intake_policy", None) == "UNIFIED_INTAKE_V1":
            # The text ID has an explicit source; a license name is never passed off as ID OCR.
            if (
                getattr(self, "intake_kind", None) == "MIXED"
                and not pages["IdCard"].get("name")
                and self.ocr_overrides.get("idNumber")
            ):
                pages["IdCard"]["name"] = pages["DrivingLicense"].get("owner", "")
            resolve = getattr(self, "identity_resolver", None)
            if resolve is not None:
                result = resolve(self.order_id)
                if result.get("state") == "REVIEW_REQUIRED":
                    raise TkNameReviewRequired(result["evidence"])
                roles = result.get("roles")
                if not isinstance(roles, dict):
                    raise TkApiError("缺少Java身份决策")
                self.quote_context["identityRoles"] = copy.deepcopy(roles)
                self._java_identity_roles = copy.deepcopy(roles)
                if roles.get("needsRoleConfirmation"):
                    raise TkOcrReviewRequired(roles.get("missingNotice") or "请确认本笔车主和投保人。")
                if not roles.get("needsRoleConfirmation"):
                    owner = roles.get("owner") or {}
                    if self.consistency_policy == "TK_OCR_CONSISTENCY_V5" and (
                        not owner.get("name") or not owner.get("idNumber")
                    ):
                        raise TkOcrReviewRequired(
                            "请补充车主"
                            + ("姓名、" if not owner.get("name") else "")
                            + "身份证号；不能使用投保人证件号替代。"
                        )
                    pages["DrivingLicense"]["owner"] = owner.get("name", pages["DrivingLicense"].get("owner", ""))
                    # A single different-name ID remains valid supplier OCR evidence.
                    # Do not erase it merely because the owner's own ID is not yet available.
                    # The later proposal mapper asks only for genuinely missing role fields.
                    if owner.get("idNumber"):
                        pages["IdCard"] = {
                            "name": owner.get("name", ""),
                            "id": owner["idNumber"],
                            "address": owner.get("certificateAddress", ""),
                        }
            self.quote_context["inputKind"] = getattr(self, "intake_kind", None) or "IMAGES"
            self._working_ocr_draft = pages
            self._persist_ocr_draft()
        self.ocr_review_snapshot = review_fields(pages)
        reason = None if supplier_ocr else review_reason(pages)
        if reason:
            raise TkOcrReviewRequired(reason)
        return pages["DrivingLicense"], pages["IdCard"]

    def _resolve_seats(self, seats, supplier, selected_model=None):
        if seats:
            return seats
        from .vehicle_lookup import active, vehicle_facts

        dto = (
            (vehicle_facts(supplier) if active(self) else supplier.get("carInfoDto"))
            if isinstance(supplier, dict)
            else None
        )
        values = [dto.get("ratedCapacity") if isinstance(dto, dict) else None]
        if isinstance(selected_model, dict):
            values.append(selected_model.get("ratedPassengerCapacity"))
            jingyou = selected_model.get("vehicleJingyou")
            if isinstance(jingyou, dict):
                values.append(jingyou.get("seat"))
        for value in values:
            text = str(value or "").strip()
            if re.fullmatch(r"[0-9]{1,3}(?:\.0)?", text) and 1 <= int(Decimal(text)) <= 100:
                return str(int(Decimal(text)))
        if self.ocr_review_enabled:
            if self.supplier_ocr_success_policy == "SUPPLIER_OCR_SUCCESS_V1":
                return ""  # The next supplier model query may supply it; never invent a seat count.
            raise TkOcrReviewRequired("车型接口未返回有效核定座位数")
        raise TkManualReview("车型接口未返回有效核定座位数")

    def _confirmed_registration_date(self, value):
        if self.supplier_ocr_success_policy == "SUPPLIER_OCR_SUCCESS_V1":
            return value  # Raw supplier OCR dates are not rewritten by an advisory date decision.
        if self.transfer_policy == "JAVA_TRANSFER_V1":
            return self.transfer_decision["registrationDate"]
        return value

    def _id_birth_and_sex(self, id_number):
        if self.supplier_ocr_success_policy != "SUPPLIER_OCR_SUCCESS_V1":
            return super()._id_birth_and_sex(id_number)
        card = (getattr(self, "_working_ocr_draft", {}) or {}).get("IdCard", {})
        number = str(id_number or "").strip()
        birth = card.get("birth") or card.get("birthDate") or ""
        sex = card.get("sex") or ""
        if len(number) == 18 and number[:17].isdigit():
            inferred_birth, inferred_sex = super()._id_birth_and_sex(number)
            birth, sex = birth or inferred_birth, sex or inferred_sex
        return self._api_date(birth), {"男": "1", "女": "2"}.get(str(sex), sex)

    def _transfer_car_fields(self):
        if self.transfer_policy not in {"JAVA_TRANSFER_V1", "JAVA_TRANSFER_V2"}:
            return super()._transfer_car_fields()
        from .business_preparation import transfer_fields

        return transfer_fields(self)

    def _validate_quote_entry(self, response):
        # Endpoint-specific official pageInfoInitError branch. Status 2 on
        # proposal endpoints has different semantics and must not reach here.
        if isinstance(response, dict) and str(response.get("status")) == "2":
            error = TkSessionExpired()
            error.supplier_feedback = business_feedback("初始化报价入口", response)
            raise self._attach_response_diagnostic(error)
        if self.transfer_policy in {"JAVA_TRANSFER_V1", "JAVA_TRANSFER_V2"}:
            self._check_expired(response)
            # Official quoteInfo.ui.js pageInfoInitError: status=0/code=1
            # means no previous quotation; proceed once to riskInit(0).
            # Code 2 (duplicate insurance), missing and unknown codes still stop.
            if (
                isinstance(response, dict)
                and str(response.get("status")) == "0"
                and str(response.get("messageCode")) == "1"
            ):
                return
            self._require_success(response, "初始化报价入口")
        else:
            super()._validate_quote_entry(response)

    def _resolve_initialized_quote(self, plan):
        if self.transfer_policy not in {"JAVA_TRANSFER_V1", "JAVA_TRANSFER_V2"}:
            return plan
        from .business_preparation import resolve_transfer

        self.quote_context["transferDecision"] = copy.deepcopy(self.transfer_decision)
        self._persist_ocr_draft()
        # Explicit refusal wins; then resolve business branches before checking
        # catalog completeness or requesting tax. Never hide the first reason.
        if isinstance(plan, dict):
            flags = plan.get("flag") or {}
            if not isinstance(flags, dict):
                raise TkManualReview("初始化险种标志格式不完整")
            if str(flags.get("noticeFlag")) == "1":
                self._validate_initialized_quote(plan)
        if self.transfer_policy == "JAVA_TRANSFER_V2":
            from .supplier_transfer import resolve

            return resolve(self, plan)
        return resolve_transfer(self, plan)

    def _validate_initialized_quote(self, plan):
        self._persist_ocr_draft()
        if getattr(self, "_text_quote_fields", None) is not None:
            self.quote_context["inputKind"] = "TEXT"
        if not isinstance(plan, dict):
            raise TkManualReview("初始化险种资料格式不完整")
        flags, other = plan.get("flag") or {}, plan.get("other") or {}
        if not isinstance(flags, dict) or not isinstance(other, dict):
            raise TkManualReview("初始化险种资料格式不完整")
        if str(flags.get("noticeFlag")) == "1":
            if business_feedback("初始化险种", plan).get("reasons"):
                raise TkSupplierRejected("初始化险种", plan)
            raise TkManualReview("初始化险种返回管控状态但缺少提示原文")
        if self.transfer_policy in {"JAVA_TRANSFER_V1", "JAVA_TRANSFER_V2"}:
            other, compulsory = plan.get("other"), plan.get("bzKindVo")
            if (
                not isinstance(other, dict)
                or not str(other.get("seats", "")).isdigit()
                or not 1 <= int(other["seats"]) <= 100
                or not isinstance(compulsory, dict)
                or compulsory.get("kindCode") != "BZ"
                or not isinstance(plan.get("flag"), dict)
                or not isinstance(plan.get("carTax"), dict)
                or not plan["carTax"].get("taxFlag")
            ):
                raise TkManualReview("初始化险种目录不完整，未调用车船税或保费计算")
            if self.prepare_mode not in {"COMPULSORY", "THIRD_PARTY", "FULL"}:
                raise TkManualReview("本笔缺少Java冻结报价模式")
            if self.prepare_mode != "COMPULSORY":
                rows = plan.get("ciKindsVo")
                if (
                    not isinstance(rows, list)
                    or not rows
                    or any(not isinstance(row, dict) or not row.get("kindCode") for row in rows)
                    or len({row["kindCode"] for row in rows}) != len(rows)
                ):
                    raise TkManualReview("初始化商业险目录不完整，未调用车船税或保费计算")

    def _validate_calculated_tax(self, response):
        self._require_success(response, "计算后读取车船税信息")

    def _smart_ocr(self, path, expected_type, label, referer):
        if not hasattr(self, "_physical_images"):
            return super()._smart_ocr(path, expected_type, label, referer)
        if self._ocr_pages is None:
            driving, card = {}, {}

            # One request lane per unique physical original. Each lane owns its
            # HTTP session; the account/order snapshot and lease guard are retained.
            diagnostics_lock = threading.Lock()
            submitted = time.monotonic()
            self.ocr_image_diagnostics = []

            def recognize_image(image):
                lane = copy.copy(self)
                lane.last_http_diagnostic = None
                lane.session = requests.Session()
                lane.session.mount("https://", OcrTimingAdapter(max_retries=0))
                queued_ms = round((time.monotonic() - submitted) * 1000)
                saved = False
                completed = False
                facts = self.ocr_document_facts.get(str(image), {})
                for attribute in ("headers", "cookies", "auth", "proxies", "verify", "cert", "trust_env"):
                    setattr(lane.session, attribute, copy.deepcopy(getattr(self.session, attribute)))
                try:
                    recovered = getattr(self, "field_recovery", {})
                    if recovered:
                        if recovered.get("orderId") != self.order_id:
                            raise TkOutcomeUnknown("字段恢复原订单不匹配")
                        fields = (recovered.get("evidence") or {}).get(str(facts.get("documentId")))
                        if isinstance(fields, dict):
                            from .ocr_recovery import merge_evidence

                            prior = (self.quote_context.get("ocrEvidenceByDocument") or {}).get(
                                str(facts.get("documentId"))
                            )
                            self._field_recovered = True
                            return {
                                "data": merge_evidence([prior or {}, {"data": fields}], reviewed_names=True),
                                "recoveredEvidence": True,
                            }
                    with observe_ocr():
                        from .vehicle_lookup import active

                        def send(path, body, *, referer):
                            if active(self):
                                from .ocr_recovery import recognize

                                return recognize(self, lane, image, body, referer)
                            return lane._post(path, body, referer=referer)

                        response = send(
                            "/rest/ocr/smartOcr",
                            {
                                "ocrDataDto": {},
                                "extraInfo": {},
                                "base64Imgs": [self._image_base64(image)],
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
                        if response.get("needsFieldRecovery"):
                            return response
                        lane._require_success(response, "识别本笔单张原图")
                        checkpoint = getattr(self, "ocr_checkpoint", None)
                        if checkpoint is not None:
                            compact = checkpoint(image, response, self.order_id)
                            if compact is not None:
                                response = compact
                            saved = True
                        completed = True
                        return response
                finally:
                    item = {
                        "documentId": facts.get("documentId"),
                        "label": facts.get("label", "证件图片"),
                        "imageIndex": self._physical_images.index(image) + 1,
                        "queueElapsedMs": queued_ms,
                        "status": "SUCCEEDED" if completed else "FAILED",
                        "checkpointSaved": saved,
                        "request": copy.deepcopy(getattr(lane, "last_http_diagnostic", None)),
                    }
                    with diagnostics_lock:
                        self.ocr_image_diagnostics.append(item)
                    lane.session.close()

            self.last_supplier_step = "/rest/ocr/smartOcr"
            with ThreadPoolExecutor(max_workers=len(self._physical_images), thread_name_prefix="tk-smart-ocr") as lanes:
                responses = list(lanes.map(recognize_image, self._physical_images))
            self._raw_ocr_responses = copy.deepcopy([r for r in responses if not r.get("recoveredEvidence")])
            failures = [
                self.ocr_document_facts[str(image)]["documentId"]
                for image, response in zip(self._physical_images, responses, strict=True)
                if response.get("needsFieldRecovery")
            ]
            if getattr(self, "consistency_policy", None) == "TK_OCR_CONSISTENCY_V5":
                self.quote_context["ocrEvidenceByDocument"] = {
                    str(self.ocr_document_facts[str(image)]["documentId"]): copy.deepcopy(response)
                    for image, response in zip(self._physical_images, responses, strict=True)
                }
            if failures:
                partial = {"DrivingLicense": {}, "IdCard": {}}
                for response in responses:
                    for page, fields in (response.get("data") or {}).items():
                        if page in partial and isinstance(fields, dict):
                            for key, value in fields.items():
                                if value not in (None, ""):
                                    if key in partial[page] and str(partial[page][key]) != str(value):
                                        raise TkOcrReviewRequired("本笔成功字段存在冲突，请引用确认对应资料。")
                                    partial[page][key] = value
                self.quote_context["ocrWorkingDraft"] = copy.deepcopy(partial)
                self.ocr_review_snapshot = review_fields(partial)
                self.quote_context["ocrSuccessfulResponses"] = copy.deepcopy(
                    [r for r in responses if not r.get("needsFieldRecovery")]
                )
                if getattr(self, "field_recovery", {}):
                    manual = self.ocr_overrides
                    car, card = partial["DrivingLicense"], partial["IdCard"]
                    missing = []
                    for title, value in (
                        (
                            "行驶证车牌或车架号",
                            car.get("brandNo") or car.get("VIN") or manual.get("licenseNo") or manual.get("vin"),
                        ),
                        ("身份证姓名", card.get("name") or manual.get("idName") or manual.get("name")),
                        ("身份证号", card.get("id") or manual.get("idNumber")),
                    ):
                        if not value:
                            missing.append(title)
                    raise TkOcrReviewRequired("请引用补充" + "、".join(missing or ["本笔未能确认的证件字段"]) + "。")
                raise TkFieldRecoveryRequired(failures)
            self._ocr_field_alternatives = []
            # Consume in original order, never completion order. No partial draft
            # is committed if a request fails or the existing conflict check fails.
            for response in responses:
                if not response.get("recoveredEvidence"):
                    self._require_success(response, "识别本笔证件原图")
                data = response.get("data")
                if not isinstance(data, dict):
                    raise TkApiError("证件接口未返回可核实字段")
                for target, name in ((driving, "DrivingLicense"), (card, "IdCard")):
                    page = data.get(name) or {}
                    if not isinstance(page, dict):
                        raise TkApiError("证件接口字段格式未经核实")
                    for key, value in page.items():
                        if value in (None, ""):
                            continue
                        if key in target and str(target[key]).strip() != str(value).strip():
                            if self.supplier_ocr_success_policy != "SUPPLIER_OCR_SUCCESS_V1":
                                raise TkManualReview("同笔证件识别字段冲突，需要核实原图")
                            self._ocr_field_alternatives.append(
                                {"page": name, "field": key, "values": [target[key], value]}
                            )
                        target[key] = value
            if (not driving or not card) and self.supplier_ocr_success_policy != "SUPPLIER_OCR_SUCCESS_V1":
                raise TkManualReview("原图未完整返回身份证和行驶证字段，请补充清晰资料")
            self._ocr_pages = {"DrivingLicense": driving, "IdCard": card}
        return copy.deepcopy(self._ocr_pages)

    def calculate_coverage(self, java_plan, verified_seat_count):
        if self._proposal_started:
            raise TkManualReview("投保已提交，不能修改本笔方案")
        selection = map_coverage(self.quote_context.get("catalog", {}), java_plan, verified_seat_count)
        expected_selection = copy.deepcopy(selection)
        progress = None
        if getattr(self, "quote_recovery_policy", None) == "QUOTE_CHECKPOINT_V1":
            basis = hashlib.sha256(
                json.dumps(
                    {"orderId": self.order_id, "plan": java_plan, "seats": verified_seat_count},
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            progress = self.quote_context.get("quoteRecovery")
            if not isinstance(progress, dict) or progress.get("revision") != self.quote_recovery_revision:
                progress = {
                    "revision": self.quote_recovery_revision,
                    "orderId": self.order_id,
                    "planHash": basis,
                    "writeOutcome": "CONFIRMED",
                }
                self.quote_context["quoteRecovery"] = progress
            if progress.get("orderId") != self.order_id or progress.get("planHash") != basis:
                raise TkManualReview("原报价版本与恢复资料不一致")
            if progress.get("writeOutcome") != "CONFIRMED":
                error = TkOutcomeUnknown("原报价步骤结果待核实，未自动重提")
                error.error_code = "QUOTE_OUTCOME_UNKNOWN"
                raise error
        car_tax_info = self._current_tax_info()
        if java_plan["mode"] != "COMPULSORY" and java_plan["nonCarIncluded"]:
            request = copy.deepcopy(selection)
            request.update(
                {
                    "chargingPost": [],
                    "riskType": "0808",
                    "initFlag": "nocarinit",
                    "orderID": self.order_id,
                    "carTaxInfo": car_tax_info,
                    "tplatformId": self.tplatform_id,
                    "tplatLoginKey": self.tplat_login_key,
                }
            )
            if progress is not None and isinstance(progress.get("selection"), dict):
                selection = copy.deepcopy(progress["selection"])
            else:
                if progress is not None:
                    progress["writeOutcome"] = "IN_FLIGHT"
                refreshed = self._decode_precise_response(
                    self._post(
                        "/rest/precise/init",
                        request,
                        referer="https://car.tk.cn/offweb/views/page/quoteInfo/quoteInfo.html",
                    ),
                    "初始化当前驾乘险产品",
                )
                selection = map_coverage(refreshed, java_plan, verified_seat_count)
                # nocarinit can omit previously verified supplementary clauses.
                refreshed_codes = {row["kindCode"] for row in selection["ciKindsVo"]}
                selection["ciKindsVo"].extend(
                    copy.deepcopy(row)
                    for row in expected_selection["ciKindsVo"]
                    if row["kindCode"] not in refreshed_codes
                    and row["kindCode"] not in {"101", "102", "103", "104", "73", "78", "79"}
                )
                if progress is not None:
                    progress["selection"] = copy.deepcopy(selection)
                    progress["writeOutcome"] = "CONFIRMED"
        self.quote_result = {}

        def verify(calculated):
            # Preserve real returned facts in Java's encrypted continuation on
            # failure; never replace them with submitted selections.
            self.quote_context["calculatedPlan"] = copy.deepcopy(calculated)
            self.quote_context["expectedSupplementary"] = {
                str(row["kindCode"]): str(row.get("isSelect", "0")) for row in expected_selection["ciKindsVo"]
            }
            self._verify_selection(calculated, expected_selection)

        self._quote_progress = progress
        try:
            self.calculate_prepared_quote(selection, validate_calculated=verify, car_tax_info=car_tax_info)
        finally:
            self._quote_progress = None
        quote_page = "https://car.tk.cn/offweb/views/page/quoteInfo/quoteInfo.html"
        if progress is None or not progress.get("saved"):
            if progress is not None:
                progress["writeOutcome"] = "IN_FLIGHT"
            self._require_success(
                self._post(
                    "/rest/save/quote",
                    {
                        "orderID": self.order_id,
                        "channelCode": self.CHANNEL,
                        "fromID": self.from_id,
                        "quoteFlag": "5",
                        "tplatformId": self.tplatform_id,
                    },
                    referer=quote_page,
                ),
                "保存本笔报价",
            )
            if progress is not None:
                progress["saved"] = True
                progress["writeOutcome"] = "CONFIRMED"
        result = self.decode_success(
            self._post(
                "/rest/init/quotation",
                {
                    "orderID": self.order_id,
                    "channelCode": self.CHANNEL,
                    "initFlag": "2",
                },
                referer="https://car.tk.cn/offweb/views/page/insurersInfo/insurersInfo.html",
            ),
            "读取电子报价数据",
        )
        self.quote_result = copy.deepcopy(result)
        return {
            "quotation": copy.deepcopy(result),
            "businessScore": self.quote_context.get("businessScore"),
        }

    @staticmethod
    def _verify_selection(calculated, expected):
        try:
            if not isinstance(calculated, dict):
                raise CoverageMappingError("保司返回险种资料不完整")
            validate_calculated_selection(calculated, expected)
        except CoverageMappingError as error:
            flags = calculated.get("flag") or {} if isinstance(calculated, dict) else {}
            if (
                (flags.get("quoteFlag") != "quote_success" or str(flags.get("noticeFlag")) != "0")
                and isinstance(calculated, dict)
                and business_feedback("计算保费", calculated).get("reasons")
            ):
                raise TkSupplierRejected("计算保费", calculated) from None
            raise TkManualReview(str(error)) from None

    def verify_current_coverage(self, java_plan, verified_seat_count):
        expected = map_coverage(self.quote_context.get("catalog", {}), java_plan, verified_seat_count)
        self._verify_selection(self.quote_context.get("calculatedPlan"), expected)

    def download_quotation(self):
        """The captured web download reads initFlag=1 then renders its native PNG."""
        if not self.quote_result or self._proposal_started:
            raise TkManualReview("需要本笔未提交投保的有效报价")
        result = self.decode_success(
            self._post(
                "/rest/init/quotation",
                {"orderID": self.order_id, "channelCode": self.CHANNEL, "initFlag": "1"},
                referer="https://car.tk.cn/offweb/views/page/quoteInfo/quoteInfo.html",
            ),
            "下载本笔报价单资料",
        )
        try:
            if Decimal(str(result["totalPremium"])) != Decimal(str(self.quote_result["totalPremium"])):
                raise TkManualReview("下载报价单金额与当前版本不一致")
        except (InvalidOperation, KeyError):
            raise TkManualReview("下载报价单缺少可核实金额") from None
        current = self.quote_result.get("quotationNo") or self.quote_result.get("quotationNoBI")
        reference = result.get("quotationNo") or result.get("quotationNoBI")
        if reference and reference != current:
            raise TkManualReview("下载报价单编号与当前版本不一致")
        original = self.quote_context.get("carInfoVo") or {}
        for field in ("licenseNo", "vinNo", "engineNo"):
            if original.get(field) and (result.get("car") or {}).get(field) != original[field]:
                raise TkManualReview("下载报价单车辆与本笔订单不一致")
        self.quote_context["downloadQuotation"] = copy.deepcopy(result)
        return copy.deepcopy(result)

    def _current_tax_info(self):
        if self.transfer_policy in {"JAVA_TRANSFER_V1", "JAVA_TRANSFER_V2"}:
            from .business_preparation import current_tax_info

            return current_tax_info(self)
        # Captured official quoteInfo.ui.js sends the selected option's cpiCode,
        # not agent/tax's UI code (the live order returns 07 -> T).
        tax = self.quote_context.get("tax") or {}
        options = [
            row
            for row in tax.get("taxFlagList", [])
            if isinstance(row, dict) and str(row.get("code")) == str(tax.get("taxFlag"))
        ]
        if len(options) != 1 or not options[0].get("cpiCode"):
            raise TkManualReview("当前计税选项缺少唯一的接口代码映射")
        flag = options[0]["cpiCode"]
        # All provided successful captures use normal taxation. Exemption,
        # reduction and already-paid branches need their own verified fields.
        if flag != "T":
            raise TkManualReview("当前计税分支需要核实完税或减免资料，不能按正常纳税代填")
        catalog_flag = (self.quote_context.get("catalog", {}).get("carTax") or {}).get("taxFlag")
        if catalog_flag != flag:
            raise TkManualReview("当前计税选项与本笔险种目录的计税状态不一致")
        return {"taxFlag": flag}

    def submit_proposal(self, confirmed_insure_info):
        """One external submission; the caller must persist SUBMITTING before calling."""
        if self._proposal_started:
            raise TkOutcomeUnknown("当前订单已经提交过投保，禁止自动重提")
        if not self.quote_result:
            raise TkApiError("需要当前版本的真实报价结果")
        self._validate_insure_info(confirmed_insure_info)
        proposal_page = "https://car.tk.cn/offweb/views/page/insurersInfo/insurersInfo.html"
        self.decode_success(
            self._post(
                "/rest/init/proposal",
                {
                    "orderId": self.order_id,
                    "channelCode": self.CHANNEL,
                    "tplatformId": self.tplatform_id,
                    "tplatLoginKey": self.tplat_login_key,
                },
                referer=proposal_page,
            ),
            "初始化投保资料",
        )
        self._require_success(
            self._post(
                "/rest/controller/entrance",
                {
                    "leadsid": "",
                    "channelCode": self.CHANNEL,
                    "orderID": self.order_id,
                    "fromID": self.from_id,
                    "insureInfo": confirmed_insure_info,
                    "tplatformId": self.tplatform_id,
                    "authFailContinueFlag": "",
                },
                referer=proposal_page,
                action_type="000012",
            ),
            "保存已确认投保资料",
        )
        self._decode_precise_response(
            self._post(
                "/rest/precise/init",
                {
                    "orderID": self.order_id,
                    "channelCode": self.CHANNEL,
                    "insureInfo": confirmed_insure_info,
                    "quoteFlag": "4",
                    "initFlag": "vip_quote",
                    "tplatformId": self.tplatform_id,
                    "tplatLoginKey": self.tplat_login_key,
                },
                referer=proposal_page,
            ),
            "校验投保会员信息",
        )
        self._proposal_started = True
        try:
            payload = {
                "channelCode": self.CHANNEL,
                "orderID": self.order_id,
                "fromID": self.from_id,
                "idcardOcrFlag": "0",
                "readTime": "",
                "channelEngages": [],
                "collectFlag": "",
                "leadsid": "",
                "retrospectId": self.retrospect_id,
            }
            raw = self._post("/rest/controller/entrance", payload, referer=proposal_page, action_type="000038")
            if isinstance(raw, dict) and "status" in raw:
                self._require_success(raw, "提交投保")
            inner = self.decrypt_business_data(raw.get("data")) if isinstance(raw, dict) else None
            if isinstance(inner, dict) and str(inner.get("status")) == "2":
                if self.proposal_status2_policy != "CONFIRM_ONCE_V1" or self._proposal_confirmation:
                    raise TkSupplierRejected("提交投保", inner)
                self._proposal_confirmation = {
                    "policy": "CONFIRM_ONCE_V1",
                    "orderId": self.order_id,
                    "requestHash": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                    "supplierFeedback": business_feedback("投保确认", inner),
                    "confirmationIssued": True,
                }
                # One captured continuation, not a transport retry. A lost
                # response, lease or second status=2 must never cause a third POST.
                raw = self._post(
                    "/rest/controller/entrance",
                    {**payload, "checkQuerySequenceNo": "0"},
                    referer=proposal_page,
                    action_type="000038",
                )
            result = self.decode_success(raw, "提交投保")
        except TkSessionExpired:
            # Preserve the authentication event; the worker still reports an
            # unknown proposal outcome and Java never replays this submission.
            raise
        except TkApiError as error:
            unknown = TkOutcomeUnknown("投保提交结果待核实，禁止自动重提")
            if isinstance(error, TkSupplierRejected):
                unknown.supplier_feedback = error.supplier_feedback
            raise unknown from None
        self.proposal_result = copy.deepcopy(result)
        if str(result.get("checkCarFlag")) != "0" and not self.post_proposal_enabled:
            raise TkManualReview(
                "投保返回车辆校验分支，需核实，不能自动二次提交", business_feedback("投保车辆校验", result)
            )
        if not result.get("proposalNo"):
            raise TkOutcomeUnknown("投保返回缺少投保单上下文，需核实")
        return copy.deepcopy(result)

    def build_confirmed_insure_info(self, fields, phone, email="", identity_roles=None):
        """Provider translation of the Java-frozen identity, never an identity-selection rule."""
        if identity_roles is not None:
            from .identity_translation import insure_info

            return insure_info(self, identity_roles, phone, email)
        for key in ("name", "idNumber", "birthDate", "sex") + (
            () if self.quote_context.get("inputKind") in {"TEXT", "MIXED"} else ("certificateAddress",)
        ):
            if not isinstance(fields.get(key), str) or not fields[key].strip():
                raise TkApiError("Java冻结身份字段不完整")
        current = self.quote_context.get("ocr", {})
        if fields["name"] != current.get("name") or fields["idNumber"] != current.get("id_number"):
            raise TkApiError("冻结身份与原报价订单不匹配")
        if fields["certificateAddress"] != (self.quote_context.get("id_card") or {}).get("address"):
            raise TkApiError("投保联系地址必须使用本笔证件地址")
        area = {
            "insuredProvinceCode": self.insured_area["provinceCode"],
            "insuredProvinceCname": self.insured_area["provinceName"],
            "insuredCityCode": self.insured_area["cityCode"],
            "insuredCityCname": self.insured_area["cityName"],
        }
        common = {
            **area,
            "insuredAddress": fields["certificateAddress"],
            "insuredNature": "1",
            "birthday": fields["birthDate"],
            "identifyNumber": fields["idNumber"],
            "identifyType": "01",
            "phoneNumber": phone,
            "sex": fields["sex"],
            "email": email,
            "isSelf": "1",
        }
        info = {
            "policyType": "1",
            "appliInfo": {
                **common,
                "appliName": fields["name"],
                "withOwner": 1,
                "invoiceFlag": "1",
                "invoiceType": "002",
                "taxpayerType": "0",
                "taxNumber": fields["idNumber"],
                "taxPayer": fields["name"],
                "bank": "",
                "taxesPhone": "",
                "account": "",
                "taxRegistAddress": "",
                "serialno": 2,
            },
            "insuredInfo": {**common, "insuredName": fields["name"], "withOwner": 0, "withApplyer": 1, "serialno": 1},
            "carOwnerVo": {
                **area,
                "insuredAddress": fields["certificateAddress"],
                "phoneNo": phone,
                "id": fields["idNumber"],
                "carOwnerNature": "1",
                "certificateType": "01",
                "name": fields["name"],
                "birthDate": fields["birthDate"],
                "sex": fields["sex"],
            },
            "contacts": {"name": "", "identifyType": "", "identifyNumber": "", "phoneNumber": ""},
            "messageSendFlag": "0",
        }
        self._validate_insure_info(info)
        return info

    def initialize_payment(self):
        """Return captured facts separately; do not infer paid/issued from a QR."""
        if self.payment_context:
            if str(self.underwriting_result.get("underWriteFlag")) != "3":
                raise TkManualReview("支付上下文缺少已核实核保分支")
            return {
                "paymentContext": copy.deepcopy(self.payment_context),
                "supplierUnderwriteFlag": self.underwriting_result.get("underWriteFlag"),
                "underwriteReason": self.underwriting_result.get("underwriteReason"),
            }
        if not self._proposal_started or not self.proposal_result.get("proposalNo"):
            raise TkApiError("需要已经核实的本笔投保结果")
        result = self.proposal_result
        if str(result.get("checkCarFlag")) != "0" and not self.inspection_context.get("underwritingApproved"):
            raise TkManualReview("车辆校验分支尚未完成")
        proposal_page = "https://car.tk.cn/offweb/views/page/insurersInfo/insurersInfo.html"
        previous = self.decode_success(
            self._post(
                "/rest/controller/entrance",
                {
                    "orderID": self.order_id,
                    "fromId": self.from_id,
                    "channelCode": self.CHANNEL,
                    "previousStep": "080000",
                },
                referer=proposal_page,
                action_type="000021",
            ),
            "读取投保后续步骤",
        )
        self.underwriting_result = copy.deepcopy(previous)
        if str(previous.get("underWriteFlag")) != "3" or str(previous.get("checkCarFlag")) == "1":
            raise TkManualReview(
                "当前响应不是已核实的自核通过分支，需Java核实核保事实后再续办", business_feedback("核保", previous)
            )
        pay_page = "https://car.tk.cn/offweb/views/page/payInfo/payInfo.html"
        self._identity(
            {
                "channelCode": self.CHANNEL,
                "tplatformId": self.tplatform_id,
                "userName": self.tplatform_id,
            },
            referer=pay_page,
        )
        fields = {
            key: result.get(key)
            for key in (
                "proposalNo",
                "payFee",
                "businessType",
                "isGetIssueCode",
                "isElectronInsure",
                "applicantNature",
                "identifyType",
                "insuredNature",
                "userNatureCode",
                "seatCount",
                "fromId",
                "acceptDate",
                "nonCarProposalNo",
                "proposalNoBI",
                "proposalNoCI",
            )
        }
        for key in ("proposalNo", "payFee", "fromId", "seatCount"):
            if not fields[key]:
                raise TkManualReview("支付所需投保上下文缺失，不能填充演示值")
        fields.update(
            {
                "channelCode": self.CHANNEL,
                "licenseNo": result.get("licenseNoEn"),
                "contactidentifytype": "01",
                "companyCode": result.get("comCode"),
            }
        )
        fields = {key: value.replace("\n", "") if isinstance(value, str) else value for key, value in fields.items()}
        self.payment_context = self.decode_success(
            self._post(
                "/rest/controller/entrance",
                fields,
                referer=pay_page,
                action_type="000052",
            ),
            "初始化支付页",
        )
        return {
            "paymentContext": copy.deepcopy(self.payment_context),
            "supplierUnderwriteFlag": previous.get("underWriteFlag"),
            "underwriteReason": previous.get("underwriteReason"),
        }

    def initialize_manual_payment(self, row):
        from .order_services import _proposal as proposal_reference

        if str(self.underwriting_result.get("underWriteFlag")) != "9":
            raise TkManualReview("本单不属于已核实的人工审核分支")
        proposal_no = proposal_reference(self)
        if row.get("orderId") != self.order_id or row.get("fullProposalNo") != proposal_no:
            raise TkManualReview("付款列表与原订单不一致")
        url = urlsplit(row.get("payUrl", ""))
        if (
            url.scheme != "https"
            or url.hostname != "car.tk.cn"
            or url.username
            or url.password
            or url.port not in (None, 443)
            or url.path != "/offweb/views/page/payInfo/payInfo.html"
        ):
            raise TkManualReview("付款页面不是已核实的泰康入口")
        values = {}
        for pair in url.query.split("&"):
            key, sep, value = pair.partition("=")
            key = unquote(key)
            if not sep or key in values:
                raise TkManualReview("付款页面参数格式不正确")
            values[key] = unquote(unquote(value))
        if values.get("cshKey") or values.get("fromPayManage"):
            raise TkManualReview("付款页面不是已核实的投保人转发分支")
        names = (
            "payFee",
            "businessType",
            "isGetIssueCode",
            "isElectronInsure",
            "applicantNature",
            "identifyType",
            "insuredNature",
            "fromId",
            "acceptDate",
            "licenseNo",
            "nonCarProposalNo",
            "proposalNoBI",
            "proposalNoCI",
            "authenticationFlag",
            "companyCode",
        )
        fields = {name: values.get(name, "") for name in names}
        fields.update(
            proposalNo=values.get("businessNo", ""),
            userNatureCode=values.get("usenaturecode", ""),
            seatCount=values.get("seatcount", ""),
            channelCode=self.CHANNEL,
            contactidentifytype=values.get("contactidentifytype", ""),
        )
        if any(not fields[key] for key in ("proposalNo", "payFee", "businessType", "fromId", "seatCount")):
            raise TkManualReview("付款页面缺少实际参数")
        if len(fields["companyCode"]) > 4:
            fields["companyCode"] = fields["companyCode"][:4]
        for optional in ("proposalNoBI", "proposalNoCI", "authenticationFlag"):
            if not fields[optional]:
                fields.pop(optional)
        page = "https://car.tk.cn/offweb/views/page/payInfo/payInfo.html"
        from . import post_proposal

        post_proposal.begin_write(self, "PAYMENT")
        self._identity(
            {"channelCode": self.CHANNEL, "tplatformId": self.tplatform_id, "userName": self.tplatform_id}, referer=page
        )
        payment = self.decode_success(
            self._post("/rest/controller/entrance", fields, referer=page, action_type="000052"), "初始化支付页"
        )
        if (
            payment.get("orderID") != self.order_id
            or payment.get("proposalNo") != proposal_no
            or str(payment.get("businessType")) != "0"
        ):
            raise TkManualReview("付款初始化与原订单或已核实支付分支不一致")
        try:
            if money_yuan(payment.get("payFee"), "付款总额") != money_yuan(
                self.quote_result.get("totalPremium"), "本版报价总额"
            ):
                raise TkManualReview("付款金额与本版已确认报价不一致")
            expires = datetime.fromisoformat(payment["paymentDeadline"].replace("Z", "+00:00"))
        except (CoverageMappingError, KeyError, AttributeError, ValueError):
            raise TkManualReview("付款金额或有效期无法核实") from None
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        if expires <= datetime.now(ZoneInfo("Asia/Shanghai")):
            raise TkManualReview("付款入口已经过期")
        self.payment_context = copy.deepcopy(payment)
        return {
            "paymentContext": copy.deepcopy(payment),
            "supplierUnderwriteFlag": self.underwriting_result["underWriteFlag"],
            "underwriteReason": self.underwriting_result.get("underwriteReason"),
        }

    def payment_forward(self):
        reference = self.payment_context.get("proposalNo")
        if not reference:
            raise TkApiError("缺少本笔支付上下文")
        try:
            expected = money_yuan(self.quote_result.get("totalPremium"), "本版报价总额")
            actual = money_yuan(self.payment_context.get("payFee"), "付款总额")
        except CoverageMappingError:
            raise TkManualReview("付款或报价金额缺少可核实值，已停止获取付款码") from None
        if expected != actual:
            raise TkManualReview("付款金额与本版已确认报价不一致，已停止获取付款码")
        data = self.decode_success(
            self._post(
                "/rest/pay/forward",
                {
                    "channelCode": self.CHANNEL,
                    "tplatformId": self.tplatform_id,
                    "proposalNo": reference,
                },
                referer="https://car.tk.cn/offweb/views/page/payInfo/payInfo.html",
            ),
            "获取二维码付款地址",
        )
        forward_url = data.get("payForwardUrl")
        if (
            not isinstance(forward_url, str)
            or not forward_url
            or len(forward_url) > 8192
            or any(c in forward_url for c in "\r\n")
        ):
            raise TkManualReview("付款地址格式不正确")
        try:
            url = urlsplit(forward_url)
            host = url.hostname
        except ValueError:
            raise TkManualReview("付款地址格式不正确") from None
        if url.scheme != "https" or host != "s.tk.cn" or url.username or url.password:
            raise TkManualReview("付款地址不属于已核实的泰康HTTPS入口")
        if str(data.get("proposalNo")) != str(reference):
            raise TkManualReview("付款地址对应的投保单与本笔不一致")
        if not data.get("paymentDeadline"):
            raise TkManualReview("未返回付款入口有效期")
        return copy.deepcopy(data)

    def _validate_insure_info(self, info):
        if not isinstance(info, dict):
            raise TkApiError("需要Java已确认的投保资料")
        for key, name_key in (
            ("appliInfo", "appliName"),
            ("insuredInfo", "insuredName"),
        ):
            value = info.get(key) or {}
            if not all(value.get(field) for field in (name_key, "identifyNumber")) or (
                self.quote_context.get("inputKind") not in {"TEXT", "MIXED"} and not value.get("insuredAddress")
            ):
                raise TkApiError("已确认身份、证件地址缺失，不能投保")
            if not re.fullmatch(r"1[3-9]\d{9}", value.get("phoneNumber", "")):
                raise TkApiError("需要本笔引用回复的业务联系电话")
            # All three captured successful flows save both emails as empty.
            # The archive application's required-email rule is not the insurer contract.
            email = value.get("email")
            if email not in (None, "") and (
                not isinstance(email, str) or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)
            ):
                raise TkApiError("已填写的联系邮箱格式不正确")
        owner = info.get("carOwnerVo") or {}
        if not all(owner.get(field) for field in ("name", "id")) or (
            self.quote_context.get("inputKind") not in {"TEXT", "MIXED"} and not owner.get("insuredAddress")
        ):
            raise TkApiError("已确认车主资料缺失")

    def export_order_context(self):
        """Sensitive continuation; Java must encrypt at rest and bind to the account/version."""
        quote_context = copy.deepcopy(self.quote_context)
        if getattr(self, "evidence_policy", None) == "PRIVATE_OCR_EVIDENCE_V1":
            if hasattr(self, "_prepare_request_cache"):
                quote_context["prepareRequestCache"] = copy.deepcopy(self._prepare_request_cache)
            if hasattr(self, "_basic_page_initialized"):
                quote_context["basicPageInitialized"] = self._basic_page_initialized
                quote_context["prepareVehicleHash"] = self._prepare_vehicle_hash
                quote_context["prepareWriteUnknown"] = self._prepare_write_unknown
        if self.supplier_ocr_success_policy == "SUPPLIER_OCR_SUCCESS_V1":
            quote_context["ocrPolicy"] = self.supplier_ocr_success_policy
        return copy.deepcopy(
            {
                "orderId": self.order_id,
                "retrospectId": self.retrospect_id,
                "quoteContext": quote_context,
                "quoteResult": self.quote_result,
                "proposalStarted": self._proposal_started,
                "proposalResult": self.proposal_result,
                "paymentContext": self.payment_context,
                "underwritingResult": self.underwriting_result,
                "preciseResponseStates": self._precise_response_states,
                "proposalConfirmation": self._proposal_confirmation,
                "materialRevision": getattr(self, "material_revision", 0),
                "inspectionContext": self.inspection_context,
                "ocrImageDiagnostics": self.ocr_image_diagnostics,
            }
        )

    def restore_order_context(self, context):
        if self.order_id or not isinstance(context, dict) or not context.get("orderId"):
            raise TkApiError("只能在未绑定订单的客户端恢复已授权上下文")
        if not isinstance(context.get("proposalStarted"), bool):
            raise TkApiError("订单上下文缺少投保执行标记")
        self.order_id = context["orderId"]
        self.retrospect_id = context.get("retrospectId", "")
        self.quote_context = copy.deepcopy(context.get("quoteContext") or {})
        self.quote_result = copy.deepcopy(context.get("quoteResult") or {})
        self._proposal_started = context["proposalStarted"]
        self.proposal_result = copy.deepcopy(context.get("proposalResult") or {})
        self.payment_context = copy.deepcopy(context.get("paymentContext") or {})
        self.underwriting_result = copy.deepcopy(context.get("underwritingResult") or {})
        self._precise_response_states = copy.deepcopy(context.get("preciseResponseStates") or [])
        self._proposal_confirmation = copy.deepcopy(context.get("proposalConfirmation") or {})
        self.material_revision = context.get("materialRevision", 0)
        self.inspection_context = copy.deepcopy(context.get("inspectionContext") or {})
        self.ocr_image_diagnostics = copy.deepcopy(context.get("ocrImageDiagnostics") or [])
