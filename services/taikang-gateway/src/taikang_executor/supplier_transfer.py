"""One leased confirmation, with Java-owned supplier flag adoption and durable permit."""

import copy

import requests

POLICY = "JAVA_TRANSFER_V2"


def resolve(client, plan):
    if getattr(client, "transfer_round_policy", None) == "BOUNDED_TRANSFER_ROUNDS_V1":
        return resolve_rounds(client, plan)
    return resolve_once(client, plan)


def resolve_once(client, plan):
    from .client import TkApiError, TkSessionExpired, TkTransportError
    from .staged_client import TkManualReview, TkOcrReviewRequired, TkOutcomeUnknown, TkSupplierRejected

    callback = getattr(client, "transfer_adoption_resolver", None)

    def uncertain(message):
        error = TkOutcomeUnknown(message)
        error.error_code = "TRANSFER_OUTCOME_UNKNOWN"
        return error

    if not callable(callback):
        raise TkManualReview("本笔缺少过户确认通道")
    adopted = callback("PLAN", initialization=plan)
    if isinstance(adopted, dict) and adopted.get("state") == "WAITING_INPUT":
        raise TkOcrReviewRequired(adopted.get("note") or "请补充过户日期。")
    value = adopted.get("adoption") if isinstance(adopted, dict) else None
    if (
        not isinstance(value, dict)
        or value.get("policy") != POLICY
        or value.get("initialDecision") != client.transfer_decision
    ):
        raise TkManualReview("本笔过户采用值与Java冻结版本不匹配")
    if adopted.get("state") == "CONFIRMED" and value.get("quotationType") == "":
        client.quote_context["transferAdoption"] = copy.deepcopy(value)
        return plan
    if adopted.get("state") != "PLANNED":
        raise uncertain("本笔过户确认结果待核实，未自动重提")
    try:
        permit = callback("START", adoption_hash=adopted["adoptionHash"])
    except (requests.RequestException, TkApiError, ValueError, KeyError, TypeError) as exc:
        raise uncertain("本笔过户确认许可待核实，未自动重提") from exc
    if permit.get("state") != "STARTED" or not permit.get("permitId") or permit.get("adoption") != value:
        raise uncertain("本笔过户确认许可未确认，未自动重提")
    request = {
        "channelCode": client.CHANNEL,
        "orderID": client.order_id,
        "initFlag": "init",
        "kindLimitCode": value["quotationType"],
        "chgOwnerInfo": copy.deepcopy(value["chgOwnerInfo"]),
        "tplatformId": client.tplatform_id,
        "tplatLoginKey": client.tplat_login_key,
    }
    if "orderVersion" in value:
        request["orderVersion"] = value["orderVersion"]
    client.quote_context["transferContinuation"] = {"state": "STARTED", "adoptionHash": adopted["adoptionHash"]}

    def record(outcome, response=None, decoded=None):
        receipt = {
            "permitId": permit["permitId"],
            "outcome": outcome,
            "requestParameters": {
                key: copy.deepcopy(request[key])
                for key in ("orderID", "initFlag", "kindLimitCode", "chgOwnerInfo", "orderVersion")
                if key in request
            },
        }
        if response is not None:
            receipt["response"] = response
        if decoded is not None:
            receipt["decoded"] = decoded
        try:
            saved = callback("COMPLETE", adoption_hash=adopted["adoptionHash"], receipt=receipt)
        except (requests.RequestException, TkApiError, ValueError, KeyError, TypeError) as exc:
            raise uncertain("本笔过户确认回执待核实，未自动重提") from exc
        if saved.get("state") != outcome or saved.get("adoption") != value:
            raise uncertain("本笔过户确认回执待核实，未自动重提")
        client.quote_context["transferContinuation"]["state"] = outcome

    try:
        response = client._post(
            "/rest/precise/init", request, referer="https://car.tk.cn/offweb/views/page/quoteInfo/quoteInfo.html"
        )
    except (TkTransportError, requests.RequestException) as exc:
        record("UNKNOWN")
        error = uncertain("本笔过户确认结果待核实，未自动重提")
        if isinstance(getattr(exc, "transport_diagnostic", None), dict):
            error.transport_diagnostic = copy.deepcopy(exc.transport_diagnostic)
        raise error from exc
    try:
        if not isinstance(response, dict) or "status" not in response:
            raise TkApiError("过户确认缺少明确回执")
        result = client._decode_precise_response(response, "处理本笔过户初始化")
    except (TkSupplierRejected, TkSessionExpired):
        record("REJECTED", response)
        raise
    except (TkApiError, ValueError, TypeError) as exc:
        record("UNKNOWN", response)
        raise uncertain("本笔过户确认回执无法确认，未自动重提") from exc
    other = result.get("other") if isinstance(result, dict) else None
    if not isinstance(other, dict):
        record("UNKNOWN", response, result)
        raise uncertain("本笔过户确认回执无法确认，未自动重提")
    if other.get("quotationType") not in (None, ""):
        record("REJECTED", response, result)
        raise TkManualReview("泰康仍要求核实过户资料，原笔停止，不循环提交")
    flags = result.get("flag") or {}
    if isinstance(flags, dict) and str(flags.get("noticeFlag")) == "1":
        record("REJECTED", response, result)
        client._validate_initialized_quote(result)
    record("CONFIRMED", response, result)
    client.quote_context["transferAdoption"] = copy.deepcopy(value)
    return result


def catalog_ready(client, result):
    if not isinstance(result, dict):
        return False
    other, flags = result.get("other"), result.get("flag")
    if not isinstance(other, dict) or not isinstance(flags, dict) or str(flags.get("noticeFlag")) == "1":
        return False
    seats = str(other.get("seats", ""))
    if not seats.isdigit() or not 1 <= int(seats) <= 100:
        return False
    bz, tax = result.get("bzKindVo"), result.get("carTax")
    if (
        not isinstance(bz, dict)
        or not isinstance(tax, dict)
        or bz.get("kindCode") != "BZ"
        or str(tax.get("taxFlag", "")) == ""
    ):
        return False
    return client.prepare_mode == "COMPULSORY" or bool(result.get("ciKindsVo"))


def resolve_rounds(client, plan):
    from .client import TkApiError, TkSessionExpired, TkTransportError
    from .staged_client import TkManualReview, TkOcrReviewRequired, TkOutcomeUnknown, TkSupplierRejected

    callback = getattr(client, "transfer_adoption_resolver", None)
    if not callable(callback):
        raise TkManualReview("本笔缺少过户确认通道")
    current = plan

    def unknown(note):
        error = TkOutcomeUnknown(note)
        error.error_code = "TRANSFER_OUTCOME_UNKNOWN"
        return error

    for attempt in range(4):
        planned = callback("PLAN", initialization=current)
        if planned.get("state") == "WAITING_INPUT":
            raise TkOcrReviewRequired(planned.get("note") or "请补充过户日期。")
        if planned.get("state") == "STOPPED":
            raise TkManualReview(planned.get("note") or "本笔过户确认待核实，未循环提交")
        value = planned.get("adoption")
        if not isinstance(value, dict) or value.get("initialDecision") != client.transfer_decision:
            raise TkManualReview("过户采用值与Java本笔初始建议不匹配")
        if planned.get("state") == "CONFIRMED":
            client.quote_context["transferAdoption"] = copy.deepcopy(value)
            return current
        if planned.get("state") != "PLANNED":
            raise unknown("本轮过户已有执行记录，未重复提交")
        if attempt >= 3:
            raise TkManualReview("本笔过户已达到3轮确认上限，请核实原单")
        permit = callback("START", adoption_hash=planned["adoptionHash"])
        if permit.get("state") != "STARTED" or not permit.get("permitId") or permit.get("adoption") != value:
            raise unknown("本轮过户许可无法确认，未自动重提")
        request = {
            "channelCode": client.CHANNEL,
            "orderID": client.order_id,
            "initFlag": "init",
            "kindLimitCode": value["quotationType"],
            "chgOwnerInfo": copy.deepcopy(value["chgOwnerInfo"]),
            "tplatformId": client.tplatform_id,
            "tplatLoginKey": client.tplat_login_key,
        }
        if "orderVersion" in value:
            request["orderVersion"] = value["orderVersion"]
        client.quote_context["transferContinuation"] = {
            "state": "STARTED",
            "round": permit["round"],
            "adoptionHash": planned["adoptionHash"],
        }

        def record(outcome, raw=None, decoded=None):
            receipt = {
                "permitId": permit["permitId"],
                "outcome": outcome,
                "requestParameters": {
                    k: copy.deepcopy(request[k])
                    for k in ("orderID", "initFlag", "kindLimitCode", "chgOwnerInfo", "orderVersion")
                    if k in request
                },
            }
            if raw is not None:
                receipt["response"] = raw
            if decoded is not None:
                receipt["decoded"] = decoded
            try:
                saved = callback("COMPLETE", adoption_hash=planned["adoptionHash"], receipt=receipt)
            except (requests.RequestException, TkApiError, ValueError, KeyError, TypeError) as exc:
                raise unknown("本轮过户结果回传待核实，未重复提交") from exc
            if saved.get("state") != outcome or saved.get("adoption") != value:
                raise unknown("本轮过户回执未确认，未重复提交")
            client.quote_context["transferContinuation"]["state"] = outcome

        try:
            raw = client._post(
                "/rest/precise/init", request, referer="https://car.tk.cn/offweb/views/page/quoteInfo/quoteInfo.html"
            )
        except (TkTransportError, requests.RequestException) as exc:
            record("UNKNOWN")
            raise unknown("本轮过户确认结果未知，未自动重提") from exc
        try:
            result = client._decode_precise_response(raw, "处理本笔过户确认")
        except (TkSupplierRejected, TkSessionExpired):
            record("REJECTED", raw)
            raise
        except (TkApiError, ValueError, TypeError) as exc:
            record("UNKNOWN", raw)
            raise unknown("本轮过户回包无法确认，未自动重提") from exc
        flags = result.get("flag") or {}
        if str(flags.get("noticeFlag")) == "1":
            record("REJECTED", raw, result)
            client._validate_initialized_quote(result)
        if catalog_ready(client, result):
            record("CONFIRMED", raw, result)
            client.quote_context["transferAdoption"] = copy.deepcopy(value)
            return result
        other = result.get("other") or {}
        if str(other.get("quotationType")) not in {"1", "2", "3"}:
            record("UNKNOWN", raw, result)
            raise unknown("确认后未返回有效目录或新的过户要求，请核实原单")
        record("NEXT_REQUIRED", raw, result)
        current = result
    raise TkManualReview("本笔过户已达到3轮确认上限，请核实原单")
