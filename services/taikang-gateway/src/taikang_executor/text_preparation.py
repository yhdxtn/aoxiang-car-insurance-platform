"""Current-order text preparation. No new order, proposal, automatic write retry or local OCR."""

import copy
import re
from datetime import date
from .vehicle_lookup import active, expand_prefill, vehicle_facts

POLICY = "FLEXIBLE_TEXT_V1"


def unified(client):
    return getattr(client, "text_policy", None) == "FLEXIBLE_TEXT_V3"


LABELS = {
    "name": "姓名",
    "idNumber": "身份证号",
    "licenseNo": "车牌",
    "vin": "车架号",
    "engineNo": "发动机号",
    "registrationDate": "初登日期",
    "issueDate": "发证日期",
    "modelName": "品牌型号",
}
# Field aliases observed in supplier model queries. Never inspect unrelated nested values.
ALIASES = {
    "licenseNo": ("licenseNo",),
    "vin": ("vinCode", "vinNo"),
    "engineNo": ("engineNo",),
    "registrationDate": ("enrollDate",),
}
PREFILL_MISS = {
    "系统提示$未成功预填车辆信息，请手动录入",
    "未成功预填车辆信息，请手动录入",
}


def normalized(key, value):
    value = str(value).strip()
    if key in {"registrationDate", "issueDate"}:
        separated = re.fullmatch(r"([0-9]{4})[-/]([0-9]{1,2})[-/]([0-9]{1,2})", value)
        if separated:
            return date(*(int(part) for part in separated.groups())).isoformat()
        compact = value.replace("-", "").replace("/", "")
        if not re.fullmatch(r"[0-9]{8}", compact):
            raise ValueError("invalid date")
        return date(int(compact[:4]), int(compact[4:6]), int(compact[6:])).isoformat()
    return value.upper() if key in {"vin", "idNumber", "licenseNo", "engineNo"} else value


def snapshot(client, fields):
    client.ocr_review_snapshot = {k: str(fields.get(k, "")) for k in LABELS}
    if unified(client):
        client.ocr_review_snapshot.update(
            {
                k: str(v)
                for k, v in fields.items()
                if k
                not in {
                    "extraMaterialText",
                    "unacceptedOptionalText",
                    "unresolvedText",
                    "unresolvedNumericTokens",
                    "unresolvedDates",
                    "inferredDateFields",
                }
            }
        )
    if active(client):
        client.ocr_review_snapshot.update(
            {key: str(fields[key]) for key in ("curbWeight", "loadWeight") if fields.get(key) not in (None, "")}
        )
    client.ocr_review_snapshot.update(
        ownerName=str(fields.get("ownerName", fields.get("name", ""))),
        idName=str(fields.get("idName", fields.get("name", ""))),
        seatCount=str(fields.get("seatCount", "")),
        certificateAddress=str(fields.get("certificateAddress", "")),
    )


def needs(client, fields, keys, *, conflict=False):
    from .staged_client import TkOcrReviewRequired

    snapshot(client, fields)
    names = "、".join(dict.fromkeys(LABELS.get(k, "资料") for k in keys))
    raise TkOcrReviewRequired(("请确认" if conflict else "请补充") + names + "。")


def decode_lookup(client, response, *, plate=False):
    # The outer envelope can carry encrypted status/data; inspect the decoded
    # business status before classifying the one verified manual-entry branch.
    from .staged_client import TkApiError

    if not isinstance(response, dict):
        raise TkApiError("车型查询回包格式错误")
    stage = "车牌车型查询" if plate else "VIN车型查询"

    def accepted(payload):
        client._check_expired(payload)
        if plate and str(payload.get("status")) == "0" and payload.get("message") in PREFILL_MISS:
            return False
        client._require_success(payload, stage)
        return True

    outer_status = "status" in response
    if outer_status and not accepted(response):
        return None
    decoded = (
        client.decrypt_business_data(response["data"])
        if isinstance(response.get("data"), str)
        else response.get("data")
    )
    if not isinstance(decoded, dict):
        raise TkApiError("车型查询业务回包格式错误")
    if "status" in decoded:
        if not accepted(decoded):
            return None
        data = decoded.get("data")
    elif outer_status:
        data = decoded
    else:
        raise TkApiError("车型查询没有明确成功状态")
    if not isinstance(data, dict):
        from .staged_client import TkManualReview

        raise TkManualReview("车型查询回包不完整。")
    return data


def lookup(client, fields, page):
    from .staged_client import TkManualReview

    anchors = {k: fields.get(k, "") for k in ("licenseNo", "vin")}
    if active(client):
        anchors.update(
            date=fields.get("registrationDate", ""),
            model=fields.get("modelName", ""),
            area=client._base_area_info(fields.get("licenseNo", "")),
            material=getattr(client, "material_revision", 0),
            account=client.tplatform_id,
        )
    saved = client.quote_context.get("textLookup")
    if isinstance(saved, dict) and saved.get("orderId") == client.order_id and saved.get("anchors") == anchors:
        if saved.get("queryMode") != "3" or saved.get("queryDate") == fields.get("registrationDate", ""):
            client._text_query_mode = saved["queryMode"]
            return copy.deepcopy(saved["data"])
    if active(client):
        # A fresh plate or VIN lookup must establish its own selection branch.
        client.quote_context.pop("prefilledLastPolicyFlag", None)
        client.quote_context.pop("prefillModelCode", None)
    base = {
        "orderID": client.order_id,
        "channelCode": client.CHANNEL,
        "fromId": client.from_id,
        "tplatformId": client.tplatform_id,
        "tplatLoginKey": client.tplat_login_key,
        "areaInfoVo": client._base_area_info(fields.get("licenseNo", "")),
    }
    data = None
    prefill = None
    if fields.get("licenseNo"):
        request = {
            **base,
            "carInfoVo": {
                "isQueryCarByOCR": "2",
                "carType": "A",
                "licenseNo": fields["licenseNo"],
                "operateFlag": "6",
                "licenseType": "02",
                "licenseTypeChinese": "小型汽车号牌",
            },
        }
        data = decode_lookup(client, client._post("/rest/car/modelinfo/query", request, referer=page), plate=True)
        client._text_query_mode = "2"
        if data is not None:
            data = expand_prefill(client, data, fields, page)
        plate_dto = vehicle_facts(data or {})
        if plate_dto.get("licenseNo") and normalized("licenseNo", plate_dto["licenseNo"]) != normalized(
            "licenseNo", fields["licenseNo"]
        ):
            needs(client, fields, ["licenseNo"], conflict=True)
    if (
        data is None
        or fields.get("vin")
        and fields["vin"] not in {str(vehicle_facts(data).get(k, "")).upper() for k in ("vinCode", "vinNo")}
    ):
        query_date = fields.get("registrationDate", "")
        dto = vehicle_facts(data or {})
        # Only a successful same-plate response without a contradictory VIN can
        # provide the VIN query's date. Keep its separate receipt for Java.
        if not query_date and not any(dto.get(k) for k in ("vinCode", "vinNo")) and dto.get("enrollDate"):
            try:
                query_date = normalized("registrationDate", dto["enrollDate"])
                prefill = copy.deepcopy(dto)
            except ValueError:
                pass
        absent = [k for k, value in (("vin", fields.get("vin")), ("registrationDate", query_date)) if not value]
        if absent:
            needs(client, fields, absent)
        request = {
            **base,
            "premiumTrialFlag": "0",
            "carInfoVo": {
                "isQueryCarByOCR": "3",
                "carType": "A",
                "enrollDate": client._api_date(query_date),
                "vinNo": fields["vin"],
                "operateFlag": "3",
            },
        }
        data = decode_lookup(client, client._post("/rest/car/modelinfo/query", request, referer=page))
        client._text_query_mode = "3"
    data = expand_prefill(client, data, fields, page) if not vehicle_facts(data) else data
    if not vehicle_facts(data):
        raise TkManualReview("车型查询缺少车辆资料。")
    client.quote_context["textLookup"] = {
        "orderId": client.order_id,
        "anchors": anchors,
        "queryMode": client._text_query_mode,
        "queryDate": fields.get("registrationDate", ""),
        "data": copy.deepcopy(data),
        "prefillCarInfoDto": prefill,
    }
    return data


def complete_fields(client, fields, data, selected_model_code=None):
    dto = vehicle_facts(data)
    returned = {}
    confirmed = getattr(client, "confirmed_text_edits", {})
    for key, aliases in ALIASES.items():
        try:
            values = {normalized(key, dto[a]) for a in aliases if dto.get(a) not in (None, "")}
            if key == "registrationDate":
                prefill = (client.quote_context.get("textLookup") or {}).get("prefillCarInfoDto")
                if isinstance(prefill, dict) and prefill.get("enrollDate"):
                    values.add(normalized(key, prefill["enrollDate"]))
        except ValueError:
            if key in confirmed:
                continue
            needs(client, fields, [key], conflict=True)
        if len(values) > 1:
            needs(client, fields, [key], conflict=True)
        if values:
            returned[key] = values.pop()
    dates = fields.get("unresolvedDates", "").splitlines()
    numeric = fields.get("unresolvedNumericTokens", "").splitlines()
    for value in numeric:
        if value == fields.get("engineNo") or value == returned.get("engineNo"):
            fields.setdefault("engineNo", value)
            continue
        try:
            dates.append(normalized("registrationDate", value))
        except ValueError:
            if not fields.get("engineNo") and not returned.get("engineNo") and len(numeric) == 1:
                fields["engineNo"] = value
            else:
                needs(client, fields, ["engineNo"], conflict=True)
    dates = sorted(dates)
    inferred = set(fields.get("inferredDateFields", "").split(","))
    # Re-evaluate raw date candidates after the engine lookup, but keep explicit labels.
    if dates:
        for key in inferred - confirmed.keys():
            fields.pop(key, None)
    if (
        len(dates) == 1
        and fields.get("registrationDate")
        and normalized("registrationDate", dates[0]) == normalized("registrationDate", fields["registrationDate"])
    ):
        dates = []  # Old Java revisions can retain an already-consumed registration token.
    if confirmed.get("registrationDate") and confirmed.get("issueDate"):
        dates = []
    if dates:
        if len(dates) in (1, 2):
            registration = fields.get("registrationDate")
            issue = fields.get("issueDate")
            if not registration and not issue:
                candidate = {"registrationDate": dates[0]}
                if len(dates) == 2:
                    candidate["issueDate"] = dates[1]
            elif registration and issue:
                if any(
                    d not in {normalized("registrationDate", registration), normalized("issueDate", issue)}
                    for d in dates
                ):
                    needs(client, fields, ["registrationDate", "issueDate"], conflict=True)
                candidate = {}
            elif len(dates) == 1:
                candidate = {"issueDate" if registration else "registrationDate": dates[0]}
            else:
                anchor = normalized("registrationDate" if registration else "issueDate", registration or issue)
                remaining = list(dates)
                if anchor not in remaining:
                    needs(client, fields, ["registrationDate", "issueDate"], conflict=True)
                remaining.remove(anchor)
                candidate = {"issueDate" if registration else "registrationDate": remaining[0]}
            for key, value in candidate.items():
                if not fields.get(key):
                    fields[key] = value
                elif normalized(key, fields[key]) != value:
                    needs(client, fields, [key], conflict=True)
            if (
                fields.get("registrationDate")
                and fields.get("issueDate")
                and normalized("registrationDate", fields["registrationDate"])
                > normalized("issueDate", fields["issueDate"])
            ):
                needs(client, fields, ["registrationDate", "issueDate"], conflict=True)
        else:
            needs(client, fields, ["registrationDate", "issueDate"], conflict=True)
    conflicts = []
    for key, value in returned.items():
        if fields.get(key):
            explicit_date = active(client) and key == "registrationDate" and key not in inferred
            if (
                normalized(key, fields[key]) != value
                and not explicit_date
                and (key in {"vin", "licenseNo"} or key not in confirmed)
            ):
                conflicts.append(key)
        else:
            fields[key] = value
    if conflicts:
        # Explicit source/Java confirmations are never overwritten by lookup.
        needs(client, fields, conflicts, conflict=True)
    loose = fields.get("unresolvedText", "").splitlines()
    loose = [s for s in loose if s not in {str(v) for v in returned.values()}]
    if loose and not unified(client) and not any(k in confirmed for k in ("name", "engineNo", "modelName")):
        needs(
            client,
            fields,
            [k for k in ("name", "engineNo", "modelName") if not fields.get(k)] or ["name"],
            conflict=True,
        )
    if not fields.get("modelName") and data.get("carModel"):
        selected = client._choose_model(data["carModel"], selected_model_code, "INITIAL")
        if selected.get("modelName"):
            fields["modelName"] = selected["modelName"]
    required = (
        ("name", "idNumber", "licenseNo", "vin", "registrationDate")
        if unified(client)
        else tuple(k for k in LABELS if k != "issueDate")
    )
    missing = [k for k in required if not fields.get(k)]
    if missing:
        needs(client, fields, missing)
    if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", str(fields["vin"]).upper()):
        needs(client, fields, ["vin"], conflict=True)
    if not re.fullmatch(r"[0-9]{17}[0-9X]", str(fields["idNumber"]).upper()):
        needs(client, fields, ["idNumber"], conflict=True)
    for key in ("registrationDate", "issueDate"):
        if fields.get(key):
            try:
                fields[key] = normalized(key, fields[key])
            except ValueError:
                needs(client, fields, [key], conflict=True)
    if not unified(client):
        fields.pop("unresolvedText", None)
    fields.pop("unresolvedDates", None)
    fields.pop("unresolvedNumericTokens", None)
    fields.pop("inferredDateFields", None)
    snapshot(client, fields)


def prepare(client, supplied, selected_model_code):
    from .staged_client import TkApiError

    if not isinstance(supplied, dict):
        raise TkApiError("文字报价资料格式不正确")
    # Original source + confirmed current-command patch; never use a previous
    # worker's merged fields as user confirmations.
    fields = copy.deepcopy(supplied)
    if not fields.get("name") and fields.get("ownerName"):
        fields["name"] = fields["ownerName"]
    fields.update(client.ocr_overrides)
    if unified(client):
        if fields.get("ownerName"):
            fields["name"] = fields["ownerName"]
        if fields.get("ownerIdNumber"):
            fields["idNumber"] = fields["ownerIdNumber"]
        if fields.get("ownerCertificateAddress"):
            fields["certificateAddress"] = fields["ownerCertificateAddress"]
    snapshot(client, fields)
    client._text_quote_fields = fields
    client._text_query_mode = "2"
    client._text_lookup_result = None
    try:
        if not fields.get("licenseNo") and not fields.get("vin"):
            needs(client, fields, ["licenseNo"])
        page = client._initialize_basic_page()
        data = lookup(client, fields, page)
        client._text_lookup_result = copy.deepcopy(data)
        complete_fields(client, fields, data, selected_model_code)
        # The Java endpoint receives supplier evidence, not Python's date decision.
        client.text_lookup_receipt = {
            "orderId": client.order_id,
            "queryMode": client._text_query_mode,
            "data": copy.deepcopy(data),
        }
        prefill = client.quote_context["textLookup"].get("prefillCarInfoDto")
        if isinstance(prefill, dict):
            client.text_lookup_receipt["prefillCarInfoDto"] = copy.deepcopy(prefill)
        driving = {"brandModel": fields.get("modelName", ""), "engineNo": fields.get("engineNo", "")}
        if active(client) and fields.get("loadWeight") not in (None, ""):
            driving["curbWeight"] = fields["loadWeight"]
        if fields.get("issueDate"):
            driving["issueDate"] = client._api_date(fields["issueDate"])
        card = {"name": fields["name"], "id": fields["idNumber"], "address": fields.get("certificateAddress", "")}
        facts = {
            "name": fields["name"],
            "id_number": fields["idNumber"],
            "license_no": fields["licenseNo"],
            "vin": fields["vin"],
            "engine_no": fields.get("engineNo", ""),
            "model_name": fields.get("modelName", ""),
            "enroll_date": client._api_date(fields["registrationDate"]),
        }
        client._prepare_vehicle(
            driving,
            card,
            facts,
            fields.get("seatCount", ""),
            client._numeric_text(fields.get("curbWeight", vehicle_facts(data).get("curingQuality")), "")
            if active(client)
            else "0",
            facts["enroll_date"],
            selected_model_code,
            None,
            page,
        )
    finally:
        client.quote_context["inputKind"] = "TEXT"
        client.quote_context["textPolicy"] = client.text_policy
        client.quote_context["textFields"] = copy.deepcopy(fields)
        client.quote_context["pageDefaultModels"] = copy.deepcopy(client._page_default_models)
        client._text_quote_fields = None
        client._text_lookup_result = None
    return copy.deepcopy(client.quote_context)
