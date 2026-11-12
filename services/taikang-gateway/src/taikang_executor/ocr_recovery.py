"""Bounded, durably admitted OCR attempts. No retry of unknown HTTP outcomes."""

import copy
import json
from datetime import datetime, timezone

from urllib3.util import Timeout


def incomplete(client, response):
    """Only current core fields; optional seats/quality can come from model lookup."""
    data = response.get("data") or {}
    if not isinstance(data, dict):
        return False
    manual = client.ocr_overrides
    card, car = data.get("IdCard") or {}, data.get("DrivingLicense") or {}
    if not card and not car:
        return True
    primary_car = any(car.get(k) for k in ("VIN", "vin", "owner", "engineNo", "regDate", "brandModel", "brandNo"))
    return bool(
        card
        and (
            not (card.get("name") or manual.get("idName") or manual.get("name"))
            or not (card.get("id") or card.get("idCode") or manual.get("idNumber"))
        )
    ) or bool(
        primary_car
        and (
            not (car.get("VIN") or car.get("vin") or manual.get("vin") or car.get("brandNo") or manual.get("licenseNo"))
            or not (car.get("engineNo") or manual.get("engineNo"))
            or not (car.get("regDate") or manual.get("registrationDate"))
            or not (car.get("owner") or manual.get("ownerName") or manual.get("name"))
        )
    )


def merge_evidence(responses, *, reviewed_names=False):
    """Adopt nonempty fields without pretending the merged view is one raw response."""
    from .staged_client import TkOcrReviewRequired

    pages = {}
    for response in responses:
        data = response.get("data") or {}
        if not isinstance(data, dict):
            continue
        for page, fields in data.items():
            if page not in {"DrivingLicense", "IdCard"} or not isinstance(fields, dict):
                continue
            target = pages.setdefault(page, {})
            for key, value in fields.items():
                if value in (None, ""):
                    continue
                if key in target and str(target[key]).strip() != str(value).strip():
                    # Date spelling alone is not a different fact.
                    from datetime import datetime

                    def normalize_date(value):
                        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
                            try:
                                return datetime.strptime(value, fmt).date()
                            except ValueError:
                                pass
                        raise ValueError("unconfirmed date")

                    try:
                        same_date = "date" in key.lower() and normalize_date(str(target[key])) == normalize_date(
                            str(value)
                        )
                    except (ValueError, TypeError):
                        same_date = False
                    if not same_date and not (
                        reviewed_names and (page, key) in {("DrivingLicense", "owner"), ("IdCard", "name")}
                    ):
                        raise TkOcrReviewRequired("同一原图两次识别的非空字段冲突，请引用确认对应字段。")
                target[key] = copy.deepcopy(value)
    return pages


def retained_view(responses):
    result = copy.deepcopy(responses[-1])
    result["data"] = merge_evidence(responses)
    if len(responses) > 1:
        result["attemptResponses"] = copy.deepcopy(responses)
    return result


def recognize(client, lane, image, body, referer):
    from .staged_client import TkOutcomeUnknown, TkOcrReviewRequired

    callback = getattr(client, "ocr_attempt", None)
    if callback is None:
        raise TkOutcomeUnknown("缺少持久识别尝试许可，未提交")
    result = None
    responses = []
    for attempt in (1, 2):
        permit = callback(image, attempt, "RESERVE", None, client.order_id)
        if not permit.get("allowed"):
            if permit.get("state") in {"SUCCEEDED", "FAILED"} and isinstance(permit.get("response"), dict):
                responses.extend(permit.get("priorResponses") or [])
                result = permit["response"]
                responses.append(result)
                if permit["state"] == "SUCCEEDED":
                    return retained_view(responses)
                continue
            if permit.get("state") in {"EXHAUSTED", "NOT_SENT"}:
                raise TkOcrReviewRequired("本图自动补试已结束，请引用补充未识别字段或补发新图。")
            raise TkOutcomeUnknown("本图原识别响应待核实，未重复调用")
        expiry = permit.get("deadline")
        if expiry:
            remaining = (
                datetime.fromisoformat(expiry.replace("Z", "+00:00")) - datetime.now(timezone.utc)
            ).total_seconds()
            if remaining < 1:
                callback(image, attempt, "NOT_SENT", None, client.order_id)
                raise TkOcrReviewRequired("本次恢复预算已到期，请引用补充未识别字段或补发新图。")
            lane.request_timeout = Timeout(total=remaining, connect=min(5, remaining), read=remaining)
        try:
            result = lane._post("/rest/ocr/smartOcr", body, referer=referer)
        except Exception:
            callback(image, attempt, "UNKNOWN", None, client.order_id)
            raise
        success = str(result.get("status")) == "1"
        explicit_failure = str(result.get("status")) == "0" and str(result.get("message", "")).strip().rstrip(
            "!！。"
        ) in {
            "信息采集失败",
            "证件信息采集失败",
        }
        needs_fields = success and incomplete(client, result)
        if not success and not explicit_failure:
            callback(image, attempt, "UNKNOWN", json.dumps(result, ensure_ascii=False), client.order_id)
            lane._require_success(result, "识别本笔原图")
        ack = callback(
            image,
            attempt,
            "FAILED" if explicit_failure or needs_fields else "SUCCEEDED",
            json.dumps(result, ensure_ascii=False),
            client.order_id,
        )
        result = ack.get("response", result)
        responses.append(result)
        merged = retained_view(responses)
        if success and not incomplete(client, merged):
            return merged
    return {**retained_view(responses), "needsFieldRecovery": True}
