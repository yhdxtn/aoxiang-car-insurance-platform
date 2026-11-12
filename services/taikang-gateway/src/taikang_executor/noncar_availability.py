"""Translate the current successful init flags; never choose or silently change a Java plan."""

POLICY = "CONTINUE_WITHOUT_UNAVAILABLE_NONCAR_V1"


def facts(catalog):
    flag = catalog.get("flag") or {}
    accident = catalog.get("driverAccidentVo")
    raw_flag = flag.get("isAccidentInsureFlag") if isinstance(flag, dict) else None
    insurer_flag = str(raw_flag) if raw_flag is not None else ""
    groups = ("carPlanInfoList", "commonPlanInfoList", "vipPlanInfoList")
    rows = []
    valid = isinstance(accident, dict) and isinstance(flag, dict)
    if valid:
        for key in groups:
            value = accident.get(key, [])
            if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
                valid = False
                break
            rows.extend(value)
    status = "UNKNOWN"
    if valid and str(flag.get("noticeFlag")) == "0":
        if insurer_flag == "0" and not rows:
            status = "UNAVAILABLE"
        elif insurer_flag == "1" and rows:
            status = "AVAILABLE"
    return {
        "policy": POLICY,
        "status": status,
        "insurerFlag": insurer_flag,
        "productCount": len(rows),
        "selectionObjectPresent": isinstance(accident, dict),
    }
