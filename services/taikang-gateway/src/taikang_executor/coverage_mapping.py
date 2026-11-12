"""Maps Java-confirmed yuan limits onto the current order's real Taikang catalog.

This module does not select a tenant/account, decide defaults, or update business
state. Java supplies the immutable selection and verified seat count.
"""

import copy
from decimal import Decimal, InvalidOperation

from taikang_executor.accident_products import validate_product


class CoverageMappingError(ValueError):
    pass


class VehicleLossUnavailable(CoverageMappingError):
    def __init__(self, message, codes=()):
        super().__init__(message)
        self.catalog_codes = tuple(sorted(codes))


LIMITS = {
    "102": "thirdParty",
    "103": "driver",
    "104": "passengerPerSeat",
    "73": "medicalThirdParty",
    "78": "medicalDriver",
    "79": "medicalPassengerPerSeat",
}
PER_SEAT = {"103", "104", "78", "79"}
PASSENGER = {"104", "79"}


def integer_yuan(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise CoverageMappingError("保额或数量格式不正确") from None
    if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
        raise CoverageMappingError("保额或数量必须为非负整数")
    return amount


def money_yuan(value, label):
    # Vehicle valuation is a monetary amount returned by the current carrier,
    # not an integer selectable third-party/per-seat coverage limit (ADR-018).
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal("0.01")):
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        raise CoverageMappingError(label + "必须为非负、精确到分的人民币金额") from None
    return amount


def map_coverage(catalog: dict, confirmed: dict, verified_seat_count: int) -> dict:
    if isinstance(verified_seat_count, bool) or not isinstance(verified_seat_count, int) or verified_seat_count < 1:
        raise CoverageMappingError("Verified seat count is required")
    supplier_seats = integer_yuan((catalog.get("other") or {}).get("seats"))
    if supplier_seats != verified_seat_count:
        raise CoverageMappingError("Supplier seat count differs from the confirmed vehicle data")
    mode = confirmed.get("mode")
    if mode not in {"COMPULSORY", "THIRD_PARTY", "FULL"}:
        raise CoverageMappingError("Unsupported confirmed mode")
    limits = {code: integer_yuan(confirmed[field]) for code, field in LIMITS.items()}
    loss = confirmed.get("vehicleLoss")
    noncar = confirmed.get("nonCarIncluded")
    if not isinstance(loss, bool) or not isinstance(noncar, bool):
        raise CoverageMappingError("Confirmed flags must be boolean")
    if mode == "FULL" and not loss or mode == "THIRD_PARTY" and loss:
        raise CoverageMappingError("Full and third-party plans must differ in vehicle loss selection")
    if mode == "COMPULSORY" and (loss or any(limits.values())):
        raise CoverageMappingError("Compulsory plan cannot contain commercial coverages")
    try:
        validate_product(confirmed, verified_seat_count)
    except ValueError as error:
        raise CoverageMappingError(str(error)) from None
    if limits["73"] and not limits["102"] or limits["78"] and not limits["103"] or limits["79"] and not limits["104"]:
        raise CoverageMappingError("Medical rider requires the corresponding parent coverage")

    payload = copy.deepcopy(catalog)
    compulsory = payload.get("bzKindVo")
    if not isinstance(compulsory, dict) or compulsory.get("kindCode") != "BZ":
        raise CoverageMappingError("Current insurer catalog lacks compulsory insurance")
    compulsory["isSelect"] = "1"
    flags = payload.get("flag")
    if not isinstance(flags, dict):
        raise CoverageMappingError("Current insurer catalog lacks coverage flags")
    flags["bzFlag"] = "1"
    flags["ciFlag"] = "0" if mode == "COMPULSORY" else "1"
    if mode == "COMPULSORY":
        payload["ciKindsVo"] = []
    else:
        rows = payload.get("ciKindsVo")
        if not isinstance(rows, list):
            raise CoverageMappingError("Current insurer catalog lacks commercial coverages")
        by_code = {row.get("kindCode"): row for row in rows}
        if len(by_code) != len(rows):
            raise CoverageMappingError("Duplicate insurer coverage code")
        if loss and "101" not in by_code:
            if not by_code or any(not isinstance(code, str) or not code.strip() for code in by_code):
                raise CoverageMappingError("Current insurer catalog lacks valid commercial coverages")
            # The remaining selected coverages must be valid before this is
            # attributed to the carrier's vehicle-loss restriction.
            map_coverage(catalog, confirmed | {"mode": "THIRD_PARTY", "vehicleLoss": False}, verified_seat_count)
            raise VehicleLossUnavailable("Current insurer catalog lacks vehicle loss coverage", by_code)
        if "101" in by_code:
            by_code["101"]["isSelect"] = "1" if loss else "0"
        for code, amount in limits.items():
            if code not in by_code:
                if amount:
                    raise CoverageMappingError("Current insurer catalog lacks selected coverage " + code)
                continue
            row = by_code[code]
            row["isSelect"] = "1" if amount else "0"
            if not amount:
                continue
            options = [
                option
                for option in row.get("amounts", [])
                if option.get("amountCname") != "不投保" and integer_yuan(option.get("amountEname")) == amount
            ]
            if len(options) != 1:
                raise CoverageMappingError("Current insurer catalog does not support limit for " + code)
            option = options[0]
            if code in PER_SEAT:
                quantity = verified_seat_count - 1 if code in PASSENGER else 1
                if quantity < 1:
                    raise CoverageMappingError("Selected passenger coverage has no passenger seats")
                row["quantity"] = str(quantity) if code in PASSENGER else quantity
                row["unitAmount"] = str(int(amount))
                row["unitAmountCN"] = option["amountCname"]
                row["quoteAmount"] = str(int(amount * quantity))
            else:
                row["quoteAmount"] = str(int(amount))
            row["quoteAmountCN"] = option["amountCname"]

    accident = payload.get("driverAccidentVo")
    if not isinstance(accident, dict):
        raise CoverageMappingError("Current insurer catalog lacks non-car selection")
    accident["isSelect"] = "1" if noncar else "0"
    accident["quantity"] = 1 if noncar else 0
    if noncar:
        plans = [
            plan
            for group in ("carPlanInfoList", "commonPlanInfoList", "vipPlanInfoList")
            for plan in accident.get(group, [])
            if plan.get("planCode") == confirmed.get("nonCarPlanCode")
        ]
        if not plans:
            raise CoverageMappingError("Confirmed non-car product is unavailable")
        prices = {Decimal(str(plan["sumPremium"])) for plan in plans}
        if len(prices) != 1 or any(not p.is_finite() or p < 0 for p in prices):
            raise CoverageMappingError("Non-car catalog price is inconsistent")
        try:
            validate_product(confirmed, verified_seat_count, next(iter(prices)))
        except ValueError as error:
            raise CoverageMappingError(str(error)) from None
        accident["selectPlanCode"] = confirmed["nonCarPlanCode"]
    return payload


def validate_calculated_selection(calculated: dict, expected: dict) -> None:
    """Check captured calculation facts, not the submitted or Java display plan.

    An outer status=1 can return an intermediate notice/default plan. Only the
    captured quote_success branch with matching risks may continue to proposal.
    Error text deliberately contains no customer/session/supplier payload.
    """
    flags = calculated.get("flag") or {}
    if flags.get("quoteFlag") != "quote_success" or str(flags.get("noticeFlag")) != "0":
        raise CoverageMappingError("保司未返回已核实的计算完成状态，需核实报价提示")
    for key in ("bzFlag", "ciFlag"):
        if str(flags.get(key)) != str(expected["flag"][key]):
            raise CoverageMappingError("保司返回的交强险或商业险选择与本笔方案不一致")
    bz = calculated.get("bzKindVo") or {}
    if bz.get("kindCode") != "BZ" or str(bz.get("isSelect")) != "1":
        raise CoverageMappingError("保司未确认本笔交强险选择")
    rows = calculated.get("ciKindsVo")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise CoverageMappingError("保司返回险种格式不完整")
    by_code = {row.get("kindCode"): row for row in rows}
    expected_rows = {row["kindCode"]: row for row in expected["ciKindsVo"]}
    if len(by_code) != len(rows) or None in by_code:
        raise CoverageMappingError("保司返回重复或缺失的险种代码")
    for code in by_code.keys() | expected_rows.keys():
        actual = by_code.get(code) or {}
        desired = expected_rows.get(code) or {}
        selected = str(actual.get("isSelect", "0"))
        wanted = str(desired.get("isSelect", "0"))
        if code not in LIMITS and code != "101":
            # Latest user rule: actual supplementary charges are displayed and
            # included in the total, not a selection blocker. Invalid money is
            # still an exception; never assume a missing premium is free.
            if selected == "1":
                money_yuan(actual.get("premium"), "附加险保费")
            continue
        if selected not in {"0", "1"} or selected != wanted:
            raise CoverageMappingError("保司返回险种勾选与本笔方案不一致（" + code + "）")
        if wanted != "1":
            continue
        # Extra service clauses use option codes (e.g. 75:1 -> 3 times), so
        # compare their selection, not an invented yuan conversion.
        if code == "101":
            if money_yuan(actual.get("quoteAmount"), "车损保额") != money_yuan(desired.get("quoteAmount"), "车损保额"):
                raise CoverageMappingError("保司返回车损保额与本笔方案不一致")
        elif code in LIMITS:
            if integer_yuan(actual.get("quoteAmount")) != integer_yuan(desired.get("quoteAmount")):
                raise CoverageMappingError("保司返回保额与本笔方案不一致（" + code + "）")
        if code in PER_SEAT:
            for key in ("unitAmount", "quantity"):
                if integer_yuan(actual.get(key)) != integer_yuan(desired.get(key)):
                    raise CoverageMappingError("保司返回每座保额或座位数与本笔方案不一致（" + code + "）")
    actual_accident = calculated.get("driverAccidentVo") or {}
    desired_accident = expected["driverAccidentVo"]
    selected = str(actual_accident.get("isSelect"))
    if selected != str(desired_accident["isSelect"]):
        raise CoverageMappingError("保司返回驾乘险选择与本笔方案不一致")
    # The supplier can retain a previous product/quantity when isSelect=0.
    # Its captured UI totals include this product only when isSelect=1.
    if selected == "1" and integer_yuan(actual_accident.get("quantity")) != integer_yuan(desired_accident["quantity"]):
        raise CoverageMappingError("保司返回驾乘险份数与本笔方案不一致")
    if selected == "1" and actual_accident.get("selectPlanCode") != desired_accident["selectPlanCode"]:
        raise CoverageMappingError("保司返回驾乘产品与本笔方案不一致")
