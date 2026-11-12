"""Endpoint-specific vehicle branches. Original supplier envelopes remain evidence."""

import copy

POLICY = "TK_OCR_CONSISTENCY_V5"


def active(client):
    return getattr(client, "consistency_policy", None) == POLICY


def prefill_active(client):
    # Unique-code matching belongs only to the captured historical-prefill branch.
    # Ordinary IMAGE/TEXT queries retain the confirmed supplier default-first rule.
    return active(client) and client.quote_context.get("prefilledLastPolicyFlag") == "1"


def vehicle_facts(data):
    for key in ("carInfoDto", "carInfoVo"):
        if isinstance(data.get(key), dict):
            return data[key]
    return {}


def model_code(model):
    return model.get("modelCode") or (model.get("vehicleJingyou") or {}).get("vehicleCode")


def expand_prefill(client, data, fields, page):
    from .staged_client import TkOcrReviewRequired

    if not active(client):
        return data
    if str(data.get("preFilledLastPolicyFlag")) != "1":
        client.quote_context.pop("prefilledLastPolicyFlag", None)
        client.quote_context.pop("prefillModelCode", None)
        return data
    initialized = client.decode_success(
        client._post(
            "/rest/init/basicInfo",
            {
                "fromId": client.from_id,
                "channelCode": client.CHANNEL,
                "tplatformId": client.tplatform_id,
                "orderManageFlag": "null",
                "orderID": client.order_id,
                "requestId": "",
                "crossRenewalFlag": "",
                "tplatLoginKey": client.tplat_login_key,
            },
            referer=page,
        ),
        "读取本笔历史预填",
    )
    car = initialized.get("carInfoVo")
    if not isinstance(car, dict) or not car:
        raise TkOcrReviewRequired("历史预填未返回本笔车辆资料，请核对车辆字段。")
    for key, aliases in {"licenseNo": ("licenseNo",), "vin": ("vinNo", "vinCode"), "engineNo": ("engineNo",)}.items():
        values = {str(car[a]).strip().upper() for a in aliases if car.get(a)}
        if fields.get(key) and values and values != {str(fields[key]).strip().upper()}:
            raise TkOcrReviewRequired("请核对本笔车辆预填与人工资料。")
    result = {
        **copy.deepcopy(data),
        "carInfoVo": copy.deepcopy(car),
        "carModel": copy.deepcopy(car.get("carModel") or []),
    }
    client.quote_context["prefilledLastPolicyFlag"] = "1"
    client.quote_context["prefillVehicleEvidence"] = copy.deepcopy(initialized)
    return result


def choose(client, candidates, explicit, stage):
    from .client import choose_model
    from .staged_client import TkManualReview

    if explicit:
        return choose_model(candidates, explicit, stage)
    if not isinstance(candidates, list) or not candidates:
        raise TkManualReview("本笔没有可核实车型，请选择实际车型。")
    anchor = client.quote_context.get("prefillModelCode") if stage == "EXACT" else None
    matches = [m for m in candidates if isinstance(m, dict) and (not anchor or model_code(m) == anchor)]
    if len(matches) != 1 or not model_code(matches[0]):
        raise TkManualReview("本笔车型不能唯一确定，请选择实际车型。")
    model = copy.deepcopy(matches[0])
    model.setdefault("modelCode", model_code(model))
    if stage == "INITIAL":
        client.quote_context["prefillModelCode"] = model["modelCode"]
    client._page_default_models[stage] = {
        "modelCode": model["modelCode"],
        "candidateCount": len(candidates),
        "selectionSource": "UNIQUE_CONFIRMED_CODE",
    }
    return model
