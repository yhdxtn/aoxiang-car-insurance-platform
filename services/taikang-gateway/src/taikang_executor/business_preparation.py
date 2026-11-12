"""Translate Java decisions and the current supplier's options, without business inference.

Field evidence: captured official basicInfo.ui.js / quoteInfo.ui.js. No fallback
POST, date inference, tax-category substitution or repeated transfer loop.
"""

import copy
import re
from datetime import date
from decimal import Decimal, InvalidOperation

import requests


def transfer_fields(client):
    from .staged_client import TkManualReview, TkOcrReviewRequired

    if not callable(getattr(client, "transfer_decision_resolver", None)):
        raise TkManualReview("本笔缺少Java过户判断通道，未继续报价")
    decision = client.transfer_decision_resolver(client.order_id)
    if (
        not isinstance(decision, dict)
        or decision.get("policy") != client.transfer_policy
        or decision.get("businessDate") != client.quote_business_date
        or decision.get("materialRevision") != client.material_revision
    ):
        raise TkManualReview("本笔过户判断与冻结版本不匹配")
    client.transfer_decision = copy.deepcopy(decision)
    client.quote_context["transferDecision"] = copy.deepcopy(decision)
    status = decision.get("status")
    if client.transfer_policy == "JAVA_TRANSFER_V2":
        flag = decision.get("initialFlag")
        if flag not in {"0", "1"} or flag != ("1" if status == "TRANSFERRED" else "0"):
            raise TkManualReview("Java初始过户参数无效")
        # UNKNOWN is retained as advice. Only the initial request uses official default 0.
        return {"chgOwnerFlag": flag, "transferDate": decision.get("transferDate", "")}
    if status == "UNKNOWN":
        if getattr(client, "text_policy", None) == "FLEXIBLE_TEXT_V1":
            raise TkOcrReviewRequired("请确认初登日期、发证日期。")
        raise TkOcrReviewRequired("本笔初登日期、发证日期缺失、异常或冲突，请核实并补充日期")
    if status not in {"TRANSFERRED", "NOT_TRANSFERRED"}:
        raise TkManualReview("Java过户判断状态无效")
    transferred = status == "TRANSFERRED"
    if transferred and (not decision.get("transferDate") or decision["transferDate"] != decision.get("issueDate")):
        raise TkManualReview("本笔缺少Java确认的过户日期")
    return {"chgOwnerFlag": "1" if transferred else "0", "transferDate": decision["transferDate"]}


def resolve_transfer(client, plan):
    from .client import TkApiError, TkSessionExpired, TkTransportError
    from .staged_client import TkManualReview, TkOutcomeUnknown, TkSupplierRejected

    if not isinstance(plan, dict):
        raise TkManualReview("初始化险种资料格式不完整")
    other = plan.get("other") or {}
    if not isinstance(other, dict):
        raise TkManualReview("初始化业务分支格式不完整")
    branch = other.get("quotationType")
    if branch in (None, ""):
        return plan
    if str(branch) not in {"1", "2", "3"}:
        raise TkManualReview("泰康返回未知的过户处理分支")
    decision = client.transfer_decision
    if not isinstance(decision, dict) or decision.get("status") not in {"TRANSFERRED", "NOT_TRANSFERRED"}:
        raise TkManualReview("本笔过户判断未确认")
    expected = "1" if decision["status"] == "TRANSFERRED" else "0"
    active = {"1": ("specialCarFlag",), "2": ("chgOwnerFlag",), "3": ("specialCarFlag", "chgOwnerFlag")}[str(branch)]
    for field in active:
        actual = other.get(field)
        if actual not in (None, "") and str(actual) != expected:
            raise TkManualReview("泰康过户状态与Java冻结判断冲突，请核实原笔")
    returned_date = other.get("transferDate")
    if returned_date and expected == "1" and client._api_date(str(returned_date)) != decision["transferDate"]:
        raise TkManualReview("泰康过户日期与本笔发证日期冲突")
    info = {
        # Official UI initial values are empty and real-time flags 0. No user
        # opted into immediate inception; supplied inception dates are unchanged.
        "startDateBZ": other.get("startDateBZ") or "",
        "startDateCIP": other.get("startDateCIP") or "",
        "chgOwnerFlagBZ": expected if str(branch) in {"1", "3"} else "",
        "chgOwnerFlagCIP": expected if str(branch) in {"2", "3"} else "",
        "InstantInureFlagCI": "0",
        "InstantInureFlagBI": "0",
        "transferDate": decision["transferDate"],
    }
    request = {
        "channelCode": client.CHANNEL,
        "orderID": client.order_id,
        "initFlag": "init",
        "kindLimitCode": str(branch),
        "chgOwnerInfo": info,
        "tplatformId": client.tplatform_id,
        "tplatLoginKey": client.tplat_login_key,
    }
    # Only forward an actual order version from the current supplier response.
    if other.get("orderVersion"):
        request["orderVersion"] = other["orderVersion"]
    client.quote_context["transferContinuation"] = {"state": "REQUESTED", "quotationType": str(branch)}
    try:
        response = client._post(
            "/rest/precise/init", request, referer="https://car.tk.cn/offweb/views/page/quoteInfo/quoteInfo.html"
        )
    except (TkTransportError, requests.RequestException) as exc:
        error = TkOutcomeUnknown("本笔过户处理结果待核实，未自动重提")
        error.error_code = "TRANSFER_OUTCOME_UNKNOWN"
        if isinstance(getattr(exc, "transport_diagnostic", None), dict):
            error.transport_diagnostic = copy.deepcopy(exc.transport_diagnostic)
        raise error from exc
    # A POST may have taken effect even when its body is absent or undecodable.
    # Keep explicit supplier refusals / confirmed expiry distinct from lost results.
    try:
        if not isinstance(response, dict) or "status" not in response:
            raise TkApiError("过户初始化响应缺少明确状态")
        result = client._decode_precise_response(response, "处理本笔过户初始化")
    except (TkSupplierRejected, TkSessionExpired):
        raise
    except (TkApiError, ValueError, TypeError) as exc:
        error = TkOutcomeUnknown("本笔过户处理回执无法确认，未自动重提")
        error.error_code = "TRANSFER_OUTCOME_UNKNOWN"
        facts = getattr(client, "last_http_diagnostic", None)
        if isinstance(facts, dict) and facts.get("path") == "/rest/precise/init":
            error.transport_diagnostic = copy.deepcopy(facts)
        raise error from exc
    if isinstance(result, dict):
        next_other = result.get("other") or {}
        if not isinstance(next_other, dict):
            raise TkManualReview("过户初始化回执格式不完整")
        if next_other.get("quotationType") not in (None, ""):
            raise TkManualReview("泰康仍要求核实过户资料，原笔停止，不循环提交")
    client.quote_context["transferContinuation"]["state"] = "CONFIRMED"
    return result


def current_tax_info(client):
    from .staged_client import TkManualReview

    tax = client.quote_context.get("tax") or {}
    if not isinstance(tax, dict) or not isinstance(tax.get("taxFlagList"), list):
        raise TkManualReview("本笔车船税选项格式不完整")
    rows = [
        row
        for row in tax.get("taxFlagList", [])
        if isinstance(row, dict) and str(row.get("code")) == str(tax.get("taxFlag"))
    ]
    if len(rows) != 1 or not isinstance(rows[0].get("cpiCode"), str) or not rows[0]["cpiCode"].strip():
        raise TkManualReview("当前计税选项缺少唯一的接口代码映射")
    code, flag = str(rows[0]["code"]), rows[0]["cpiCode"]
    catalog = client.quote_context.get("catalog") or {}
    if not isinstance(catalog, dict) or not isinstance(catalog.get("carTax"), dict):
        raise TkManualReview("本笔计税目录格式不完整")
    if catalog["carTax"].get("taxFlag") != flag:
        raise TkManualReview("当前计税选项与本笔险种目录的计税状态不一致")
    result = {"taxFlag": flag}
    # Only the confirmed UI categories below are automated. Unknown mappings
    # stay on the original order; never downgrade a category to normal T.
    if code == "07":
        if flag != "T":
            raise TkManualReview("正常纳税的实际接口代码不一致")
        return result
    if code not in {"03", "04", "05"}:
        raise TkManualReview("当前计税分支尚未有完整协议证据，请核实原笔")
    flags = catalog.get("flag") or {}
    if not isinstance(flags, dict):
        raise TkManualReview("本笔续保计税标志格式不完整")
    renewal = str(flags.get("renewalFlag")) == "1"
    needs_fields = tax.get("taxType") == "local_tax_flag" or renewal
    if not needs_fields:
        # Same selected category, supplier already holds its tax facts. This
        # follows the official UI condition and does not invent proof fields.
        return result

    def required(key):
        value = tax.get(key)
        if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool) or not str(value).strip():
            raise TkManualReview("本笔完税或减免税资料不完整，请核实原笔")
        return str(value).strip()

    def only_option(key):
        options = tax.get(key)
        # No selected-value protocol exists for multiple returned candidates.
        if not isinstance(options, list) or len(options) != 1 or not isinstance(options[0], dict):
            raise TkManualReview("本笔车船税资料存在多个或缺失选项，请核实原笔")
        return options[0]

    def option_value(key, field):
        value = only_option(key).get(field)
        if not isinstance(value, str) or not value.strip():
            raise TkManualReview("本笔车船税选项缺少真实代码或名称")
        return value

    def actual_date(key):
        value = required(key)
        try:
            date.fromisoformat(value)
        except ValueError:
            raise TkManualReview("本笔车船税凭证日期无效") from None
        return value

    if code in {"04", "05"}:
        # Official T-platform renewals retain already persisted relief facts.
        if client.com_code == "0122" or renewal and client.tplatform_id:
            return result
        result.update(
            {
                "deDuctiondueCode": option_value("deDuctiondueCode", "cpiCode"),
                "deDuctiondueType": option_value("exemptionType" if code == "05" else "reductionType", "code"),
                "taxDepartmentCode": option_value("taxDepartment", "code"),
                "taxDepartment": option_value("taxDepartment", "value"),
                "deDuctionDocumentNumber": option_value("deDuctionDocumentNumber", "code"),
            }
        )
        if code == "04":
            scheme = result["deDuctiondueType"]
            if scheme == "A":
                value = required("deDuction")
                try:
                    amount = Decimal(value)
                    valid = amount.is_finite() and amount >= 0 and amount.as_tuple().exponent >= -2
                except InvalidOperation:
                    valid = False
                if not valid:
                    raise TkManualReview("本笔减税金额无效")
                result["deDuction"] = value
            elif scheme == "P":
                value = required("deDuctiondueProportion")
                if not re.fullmatch(r"[0-9]{1,3}", value) or not 0 <= int(value) <= 100:
                    raise TkManualReview("本笔减税比例无效")
                result["deDuctiondueProportion"] = value
            else:
                raise TkManualReview("本笔减税方案代码未经确认")
    else:
        result.update(
            {
                "taxDocumentNumber": required("paidNumber"),
                "taxDepartmentCode": option_value("taxDepartment", "code"),
                "taxDepartment": option_value("taxDepartment", "value"),
                "taxPaidAreaCode": option_value("taxProvince", "code"),
                "taxDocumentDate": actual_date("taxDocumentDate"),
            }
        )
        if tax.get("taxType") == "all_tax_flag":
            result.update({"taxStartDate": actual_date("taxStartDate"), "taxEndDate": actual_date("taxEndDate")})
            if result["taxStartDate"] > result["taxEndDate"]:
                raise TkManualReview("本笔车船税所属起止日期不一致")
    return result
