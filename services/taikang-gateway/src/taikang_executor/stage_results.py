"""Normalize supplier facts for Java; no business state, default selection or persistence."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from taikang_executor.client import TkApiError
from taikang_executor.accident_products import validate_product


def money(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise TkApiError("接口金额缺失或格式不正确") from None
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise TkApiError("接口金额不是有效人民币金额")
    return format(amount, ".2f")


def context(client, data):
    return {
        "tenantId": str(data["tenantId"]),
        "accountId": str(data["accountId"]),
        "credentialVersion": data["credentialVersion"],
        "orderContext": client.export_order_context(),
    }


def prepared(client, data):
    state = client.quote_context
    ocr, card, car, catalog = state["ocr"], state["id_card"], state["carInfoVo"], state["catalog"]
    supplier_ocr = state.get("ocrPolicy") == "SUPPLIER_OCR_SUCCESS_V1"
    seats = int(catalog["other"]["seats"]) if supplier_ocr else int(car["selectedSeat"])
    if seats < 1 or seats != int(catalog["other"]["seats"]):
        raise TkApiError("当前订单座位数与证件资料不一致")
    amounts = {}
    for row in catalog.get("ciKindsVo", []):
        code = str(row.get("kindCode"))
        if code in {"102", "103", "104", "73", "78", "79"}:
            amounts[code] = [
                str(Decimal(str(option["amountEname"])))
                for option in row.get("amounts", [])
                if str(option.get("amountEname")) != "2"
            ]
    from .noncar_availability import POLICY, facts

    if data.get("nonCarAvailabilityPolicy") == POLICY:
        state["nonCarAvailability"] = facts(catalog)
    products = {}
    accident = catalog.get("driverAccidentVo") or {}
    for group in ("carPlanInfoList", "commonPlanInfoList", "vipPlanInfoList"):
        for product in accident.get(group, []):
            code, price = product["planCode"], money(product["sumPremium"])
            if code in products and products[code] != price:
                raise TkApiError("当前驾乘险产品价格不一致")
            products[code] = price
    return {
        "fields": {
            **(
                {
                    k: str(v)
                    for k, v in (state.get("textFields") or {}).items()
                    if k
                    in {
                        "vehicleAddress",
                        "vehicleType",
                        "useNature",
                        "curbWeight",
                        "loadWeight",
                        "tractionWeight",
                        "fuelType",
                        "licenseNoBack",
                        "idName",
                        "ownerName",
                        "ownerIdNumber",
                        "ownerCertificateAddress",
                        "applicantName",
                        "applicantIdNumber",
                        "applicantAddress",
                        "nation",
                        "birth",
                    }
                }
                if state.get("textPolicy") == "FLEXIBLE_TEXT_V3"
                else {}
            ),
            **(
                {"applicantName": str((state["identityRoles"].get("applicant") or {}).get("name") or "")}
                if isinstance(state.get("identityRoles"), dict)
                else {}
            ),
            "name": ocr["name"],
            **(
                {"ownerName": str(ocr.get("owner_name") or ""), "idName": str(ocr.get("id_name") or "")}
                if supplier_ocr
                else {}
            ),
            "idNumber": ocr["id_number"],
            "licenseNo": ocr["license_no"],
            "vin": ocr["vin"],
            "engineNo": ocr["engine_no"],
            "modelName": ocr["model_name"],
            "vehicleColorCode": str(car.get("colorCode") or "999"),
            "registrationDate": ocr["enroll_date"],
            **({"issueDate": state["transferDecision"]["issueDate"]} if state.get("transferDecision") else {}),
            "certificateAddress": card.get("address") or "",
            **(
                {"email": state["textFields"]["email"]}
                if state.get("inputKind") == "TEXT" and (state.get("textFields") or {}).get("email")
                else {}
            ),
            "birthDate": state["birth"],
            "sex": str(state["sex"]),
        },
        "seatCount": seats,
        "availableAmounts": amounts,
        "nonCarPremiums": products,
        "context": context(client, data),
    }


def quoted(client, data, result):
    quote = result["quotation"]
    ref = quote.get("quotationNo") or quote.get("quotationNoBI")
    if not isinstance(ref, str) or not ref.strip():
        raise TkApiError("当前报价没有真实单号")
    bz, ci, accident = (
        quote.get("orderInfoVoBZ") or {},
        quote.get("orderInfoVoCI") or {},
        quote.get("driverAccidentVo") or {},
    )
    amounts = {"交强险": money(bz["jqPremium"]), "车船税": money(bz["carTax"]["sumPayment"])}
    if data["coverage"]["mode"] != "COMPULSORY":
        amounts["商业险"] = money(ci["syPremium"])
    for row in ci.get("allKinds", []):
        if str(row.get("kindCode")) in {"74", "75"}:
            continue
        if row.get("kindCName") and row.get("premium") not in (None, ""):
            amounts[str(row["kindCName"])] = money(row["premium"])
    # Use actual selected supplementary facts. Commercial premiums already
    # include these fees: display them without adding them a second time.
    services = {"74": "道路救援服务", "75": "车辆安全检测服务"}
    expected = client.quote_context.get("expectedSupplementary")
    if expected is None:
        expected = {
            str(row["kindCode"]): str(row.get("isSelect", "0"))
            for row in (client.quote_context.get("catalog") or {}).get("ciKindsVo", [])
        }
    quoted_rows = {str(row.get("kindCode")): row for row in ci.get("allKinds", [])}
    for row in (client.quote_context.get("calculatedPlan") or {}).get("ciKindsVo", []):
        code = str(row.get("kindCode"))
        if code not in {"101", "102", "103", "104", "73", "78", "79"} and str(row.get("isSelect")) == "1":
            fee = money(row.get("premium"))
            name = str(
                row.get("kindCName")
                or quoted_rows.get(code, {}).get("kindCName")
                or services.get(code)
                or "保司附加项目（" + code + "）"
            )
            if len(name) > 200 or "\n" in name or "\r" in name:
                raise TkApiError("附加项目名称格式异常")
            count_text = ""
            try:
                count = Decimal(str(row.get("quantity")))
                if count.is_finite() and count >= 0 and count == count.to_integral_value():
                    count_text = "，" + (str(int(count)) + "次" if code in services else "数量" + str(int(count)))
            except InvalidOperation:
                pass
            # Replace an unannotated entry with the actual selection/counts.
            amounts.pop(name, None)
            if Decimal(fee) == 0:
                amounts[name + "（免费附赠" + count_text + "）"] = fee
            else:
                displayed = quoted_rows.get(code)
                if displayed is None or money(displayed.get("premium")) != fee:
                    raise TkApiError("新增附加费用与最终报价明细不一致")
                prefix = "新增收费附加项：" if expected.get(code) != "1" or code in services else "附加项目："
                amounts[prefix + name + count_text] = fee
    if data["coverage"]["nonCarIncluded"]:
        if accident.get("selectPlanCode") != data["coverage"]["nonCarPlanCode"] or str(accident.get("isSelect")) != "1":
            raise TkApiError("最终报价的驾乘险选择与冻结方案不匹配")
        amounts["驾乘险"] = money(accident["premium"])
        if (
            data["coverage"].get("nonCarPolicyVersion", 0) == 0
            and data["coverage"]["mode"] == "COMPULSORY"
            and amounts["驾乘险"] != "49.00"
        ):
            raise TkApiError("单交最终驾乘保费不是已确认的49元，需人工核实")
        try:
            validate_product(data["coverage"], data["prepared"]["seatCount"], Decimal(amounts["驾乘险"]))
        except ValueError:
            raise TkApiError("最终驾乘保费或产品与冻结规则不一致，需人工核实") from None
        expected_price = (data.get("prepared") or {}).get("nonCarPremiums", {}).get(data["coverage"]["nonCarPlanCode"])
        if expected_price is None or money(expected_price) != amounts["驾乘险"]:
            raise TkApiError("最终驾乘保费与本笔已确认产品价格不一致")
    elif data["coverage"].get("nonCarPolicyVersion") == 2:
        if str(accident.get("isSelect")) != "0":
            raise TkApiError("最终报价仍包含未选驾乘险，需人工核实")
    total = money(quote["totalPremium"])
    components = sum(Decimal(amounts.get(key, "0.00")) for key in ("交强险", "车船税", "商业险", "驾乘险"))
    if components != Decimal(total):
        raise TkApiError("报价总额与交强险、车船税、商业险及驾乘险合计不一致")
    additional = sum(
        Decimal(value) for key, value in amounts.items() if key.startswith(("新增收费附加项：", "附加项目："))
    )
    if additional > Decimal(amounts.get("商业险", "0.00")):
        raise TkApiError("附加费用未计入商业险合计")
    return {
        "quotationRef": ref,
        "totalPremium": total,
        "businessScore": result.get("businessScore"),
        "amounts": amounts,
        "context": context(client, data),
    }


def payment(client, data, result, underwriting, manual_row=None):
    raw = (
        result.get("paymentDeadline")
        if manual_row is not None
        else result.get("expireDate") or result.get("paymentDeadline")
    )
    if not isinstance(raw, str):
        raise TkApiError("付款接口未返回可核实的有效期")
    try:
        expires = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise TkApiError("付款码有效期格式未经确认") from None
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    reference = result.get("proposalNo")
    if reference != client.payment_context.get("proposalNo"):
        raise TkApiError("付款码投保单号与原订单不匹配")
    if money(client.payment_context.get("payFee")) != money(client.quote_result.get("totalPremium")):
        raise TkApiError("付款金额与本版已确认报价不一致")
    # 000052 returns the plain payment fee; pay/forward only returns a URL/deadline.
    # Never substitute the old quoted total for a changed underwriting fee.
    payment_result = {
        "proposalRef": reference,
        "underwriteFlag": str(underwriting["supplierUnderwriteFlag"]),
        "totalPremium": money(client.payment_context["payFee"]),
        "expiresAt": expires.isoformat(),
        "context": context(client, data),
    }
    if manual_row is not None:
        raw_initialized_deadline = client.payment_context.get("paymentDeadline")
        try:
            initialized_deadline = datetime.fromisoformat(raw_initialized_deadline.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            raise TkApiError("付款初始化有效期不可核实") from None
        if initialized_deadline.tzinfo is None:
            initialized_deadline = initialized_deadline.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        if min(expires, initialized_deadline) <= datetime.now(ZoneInfo("Asia/Shanghai")):
            raise TkApiError("付款入口已过期")
        payment_result["expiresAt"] = min(expires, initialized_deadline).isoformat()
        payment_result["paymentContinuation"] = {
            "listOrderId": manual_row["orderId"],
            "listProposalNo": manual_row["fullProposalNo"],
            "initializeOrderId": client.payment_context["orderID"],
            "initializeProposalNo": client.payment_context["proposalNo"],
            "initializePayFee": money(client.payment_context["payFee"]),
            "initializePaymentDeadline": initialized_deadline.isoformat(),
            "forwardProposalNo": result["proposalNo"],
            "forwardPaymentDeadline": expires.isoformat(),
        }
    return payment_result
