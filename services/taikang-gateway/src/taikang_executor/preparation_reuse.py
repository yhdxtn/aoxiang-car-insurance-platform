"""Exact current-order preparation checkpoints, never quote/proposal replay."""

import copy
import hashlib
import json

from .supplier_evidence import POLICY

CACHE_PATHS = frozenset(
    {
        "/rest/car/modelinfo/query",
        "/rest/car/modelinfo/checkVehicleType",
        "/rest/ocr/saveOcrPrefillInfo",
        "/rest/save/basicInfo",
        "/rest/init/quote",
        "/rest/precise/init",
        "/rest/agent/tax",
    }
)
ENCRYPTED_DATA_PATHS = frozenset({"/rest/car/modelinfo/query", "/rest/precise/init"})


def semantic(value):
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items() if k not in {"tplatLoginKey", "tkCarRequestToken"}}
    if isinstance(value, list):
        return [semantic(v) for v in value]
    return value


def post(client, send, path, body, **kwargs):
    if (
        not getattr(client, "_preparing", False)
        or getattr(client, "evidence_policy", None) != POLICY
        or path not in CACHE_PATHS
        or "chgOwnerInfo" in body
    ):
        return send(path, body, **kwargs)
    from .client import TkApiError, TkTransportError, TkSessionExpired
    from .staged_client import TkOutcomeUnknown, TkSupplierRejected
    import requests

    cache = client._prepare_request_cache
    basis = {"path": path, "body": semantic(body)}
    if path in {"/rest/init/quote", "/rest/precise/init", "/rest/agent/tax"}:
        basis["vehicle"] = client._prepare_vehicle_hash
    key = hashlib.sha256(
        json.dumps(basis, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    mutating = path in {"/rest/ocr/saveOcrPrefillInfo", "/rest/save/basicInfo", "/rest/init/quote", "/rest/precise/init"}
    if mutating and client._prepare_write_unknown:
        error = TkOutcomeUnknown("原订单准备步骤结果待核实，未重复提交")
        error.error_code = "PREPARE_WRITE_OUTCOME_UNKNOWN"
        raise error
    if key in cache:
        if path == "/rest/save/basicInfo":
            # The current vehicle may have been changed since this older success.
            # Reuse only the latest confirmed save, never restore a stale save.
            if key == client._prepare_vehicle_hash:
                return copy.deepcopy(cache[key])
        elif path == "/rest/ocr/saveOcrPrefillInfo":
            if key == client._prepare_ocr_prefill_hash:
                return copy.deepcopy(cache[key])
        else:
            return copy.deepcopy(cache[key])
    if mutating:
        client._prepare_write_unknown = key
    try:
        response = send(path, body, **kwargs)
    except (TkSessionExpired, TkSupplierRejected):
        if mutating:
            client._prepare_write_unknown = None  # Explicit rejection is not a lost write response.
        raise
    except (TkTransportError, requests.RequestException) as exc:
        if mutating:
            error = TkOutcomeUnknown("本笔准备步骤响应未知，未自动重提")
            error.error_code = "PREPARE_WRITE_OUTCOME_UNKNOWN"
            raise error from exc
        raise
    # Explicit responses end the unknown transport state. Only a verified
    # business success becomes a reusable checkpoint.
    if mutating:
        client._prepare_write_unknown = None
    accepted = isinstance(response, dict) and str(response.get("status")) in (
        {"1", "4", "10"} if path == "/rest/precise/init" else {"1"}
    )
    if accepted and path in ENCRYPTED_DATA_PATHS and isinstance(response.get("data"), str):
        try:
            decoded = client.decrypt_business_data(response["data"])
        except TkApiError:
            # Optional reuse must not change the endpoint caller's validation.
            # Return the original response uncached; its normal decoder still
            # rejects genuinely malformed encrypted business data.
            accepted = False
        else:
            accepted = isinstance(decoded, dict) and ("status" not in decoded or str(decoded.get("status")) == "1")
    if accepted:
        cache[key] = copy.deepcopy(response)
        if path == "/rest/save/basicInfo":
            client._prepare_vehicle_hash = key
        elif path == "/rest/ocr/saveOcrPrefillInfo":
            client._prepare_ocr_prefill_hash = key
    return response
