"""Read-only order service contracts recovered from the supplied and official UI APIs.

No proposal, payment, signature or retry is performed by these operations.
"""

import base64
import binascii
import hashlib
import json

from Crypto.Cipher import AES
from Crypto.Util import Counter

from taikang_executor.client import TkApiError, TkSessionExpired
from taikang_executor.staged_client import TkSupplierRejected, business_feedback

MAX_PDF_BYTES = 15 * 1024 * 1024
QUERY_PATHS = {
    "ISSUED": "/rest/order/management/agent/completeAgent",
    "WAITING_PAYMENT": "/rest/order/management/agent/paymentAgent",
    "PENDING": "/rest/order/management/agent/pendingAgent",
}
POLICY_PATH = "/rest/image/download/policy"
ORDER_REFERER = "https://car.tk.cn/offwebNew/"
# Official production offwebNew config.keyCtr and decryptoCtr. These public
# protocol constants are distinct from the quote API's CBC transport.
ORDER_DATA_KEY = b"9v3dIY7xRZkGQJNc"
ORDER_DATA_IV = b"4qX2nZ3WkY7w1W6l"


def decode_order_response(payload):
    if isinstance(payload, dict) and str(payload.get("status")) != "1":
        raise TkSupplierRejected("订单查询", payload)
    if not isinstance(payload, dict):
        raise TkApiError("订单查询没有明确成功状态")
    value = payload.get("data")
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        raise TkApiError("订单查询业务数据为空")
    try:
        encrypted = base64.b64decode(value, validate=True)
        # CryptoJS CTR increments only the final 32-bit word of its IV.
        counter = Counter.new(32, prefix=ORDER_DATA_IV[:12], initial_value=int.from_bytes(ORDER_DATA_IV[12:], "big"))
        cipher = AES.new(ORDER_DATA_KEY, AES.MODE_CTR, counter=counter)
        result = json.loads(cipher.decrypt(encrypted).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise TkApiError("订单查询CTR业务数据解密失败") from error
    if not isinstance(result, dict):
        raise TkApiError("订单查询业务响应格式错误")
    return result


def _proposal(client):
    proposal = client.proposal_result
    value = (proposal.get("data") or {}).get("proposalNo") if isinstance(proposal.get("data"), dict) else None
    value = value or proposal.get("proposalNo")
    if not isinstance(value, str) or not value.strip() or not client.order_id:
        raise TkApiError("本单缺少已提交投保单号，不能查询其他订单")
    return value


def _query_body(client, reference):
    return {
        "fromId": client.from_id,
        "channelCode": client.CHANNEL,
        "pageNo": 1,
        "pageSizePerPage": 15,
        "tplatformId": client.tplatform_id,
        "tplatLoginKey": client.tplat_login_key,
        "subAccountFlag": "",
        "findStartDate": "",
        "findEndDate": "",
        "licenseNo": "",
        "engineNo": "",
        "frameNo": "",
        "appliName": "",
        "insuredName": "",
        "fullProposalNo": reference,
        "comCodeList": [],
        "oaId": "",
    }


def query_order(client):
    reference = _proposal(client)
    evidence = []
    messages = []
    origins = []
    for state, path in QUERY_PATHS.items():
        body = _query_body(client, reference)
        if state == "WAITING_PAYMENT":
            body["transactionNo"] = ""
        if state == "PENDING":
            body.update(queryType="", orderTypeQueryFlag="1")
        payload = client._post(path, body, referer=ORDER_REFERER, action_type="queryClaimData")
        client._check_expired(payload)
        if isinstance(payload, dict) and str(payload.get("status")) == "0":
            # Official list views have a status=0 catch path. It proves no
            # completed business fact; still try the other exact scoped lists.
            # Do not turn it into a paid/issued state or an empty success.
            feedback = business_feedback("订单查询", payload)
            for origin in feedback.get("reasonOrigins", []):
                reason = feedback["reasons"][origin["reasonIndex"]]
                if reason not in messages:
                    messages.append(reason)
                mapped = {**origin, "reasonIndex": messages.index(reason), "category": state}
                if mapped not in origins:
                    origins.append(mapped)
            evidence.append(
                {
                    "category": state,
                    "matched": False,
                    "status": "0",
                    "message": payload.get("message") or payload.get("msg"),
                }
            )
            continue
        try:
            result = decode_order_response(payload)
        except TkSupplierRejected as error:
            for origin in error.supplier_feedback.get("reasonOrigins", []):
                reason = error.supplier_feedback["reasons"][origin["reasonIndex"]]
                if reason not in messages:
                    messages.append(reason)
                origins.append({**origin, "reasonIndex": messages.index(reason), "category": state})
            reasons = list(dict.fromkeys(messages + error.supplier_feedback.get("reasons", [])))
            if reasons:
                error.supplier_feedback.update(reason=reasons[0], reasons=reasons, reasonOrigins=origins)
            raise
        rows = result.get("list")
        if not isinstance(rows, list):
            raise TkApiError("订单查询缺少真实列表，不能判断付款或签发")
        # An exact server filter is still verified locally. Never select newest/customer matches.
        matches = [
            row
            for row in rows
            if isinstance(row, dict)
            and row.get("orderId") == client.order_id
            and row.get("fullProposalNo") == reference
        ]
        if len(matches) > 1:
            raise TkApiError("本单查询结果不唯一，需核实")
        evidence.append({"category": state, "matched": bool(matches)})
        if not matches:
            continue
        row = matches[0]
        policies = policy_references(row, client.CHANNEL) if state == "ISSUED" else []
        if state == "ISSUED" and not policies:
            state = "COMPLETED_WITHOUT_POLICY"
        return {
            "orderId": client.order_id,
            "proposalNo": reference,
            "state": state,
            "paymentState": "UNPAID" if state == "WAITING_PAYMENT" else "UNKNOWN",
            "policies": policies,
            "supplierRow": row,
            "evidence": evidence,
            "supplierFeedback": {"stage": "订单查询", "reasons": messages, "reasonOrigins": origins},
        }
    return {
        "supplierFeedback": {"stage": "订单查询", "reasons": list(dict.fromkeys(messages)), "reasonOrigins": origins},
        "orderId": client.order_id,
        "proposalNo": reference,
        "state": "UNKNOWN",
        "paymentState": "UNKNOWN",
        "policies": [],
        "evidence": evidence,
    }


def policy_references(row, channel):
    policies = []
    for kind, key in (("CI", "subPolicyNoCi"), ("BI", "subPolicyNoBi")):
        if isinstance(row.get(key), str) and row[key]:
            policies.append({"kind": kind, "subPolicyNo": row[key]})
    noncar = row.get("nonVehiclePaymentVos") or []
    if not isinstance(noncar, list):
        raise TkApiError("本单非车保单目录格式不正确")
    for item in noncar:
        if isinstance(item, dict) and item.get("productCode") == "0810" and item.get("subPolicyNoJcbEnc"):
            if not isinstance(item["subPolicyNoJcbEnc"], str):
                raise TkApiError("本单驾乘保单引用格式不正确")
            policies.append({"kind": "JYX", "subPolicyNo": item["subPolicyNoJcbEnc"]})
    if len(policies) > 3 or len({p["kind"] for p in policies}) != len(policies):
        raise TkApiError("本单保单类型重复或超过已核实目录")
    for policy in policies:
        # These values come from the uniquely matched completed row, never the caller.
        if not isinstance(row.get("enteringDate"), str) or not row["enteringDate"].strip():
            raise TkApiError("已签发保单缺少官方下载上下文")
        policy.update(inputDate=row["enteringDate"], channelCode=channel)
    return policies


def decode_policy_pdf(payload):
    if not isinstance(payload, dict) or str(payload.get("status")) != "1":
        raise TkApiError("电子保单下载未返回明确成功状态")
    value = payload.get("data")
    if not isinstance(value, str) or len(value) > (MAX_PDF_BYTES + 2) // 3 * 4:
        raise TkApiError("电子保单内容缺失或过大")
    try:
        content = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise TkApiError("电子保单不是有效Base64文件") from None
    if not 8 <= len(content) <= MAX_PDF_BYTES or not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]:
        raise TkApiError("下载内容不是完整PDF电子保单")
    return content


def download_policy(client, policy):
    client.request_guard()
    client.last_supplier_step = POLICY_PATH
    params = {key: policy[key] for key in ("channelCode", "inputDate", "subPolicyNo")}
    params["userId"] = client.tplat_login_key
    # Fixed official origin, no URL supplied by the order and no redirects/cookie leakage.
    with client.session.get(
        client.BASE_URL + POLICY_PATH,
        params=params,
        headers=client._headers(ORDER_REFERER),
        timeout=(15, 120),
        stream=True,
        allow_redirects=False,
    ) as response:
        if response.status_code == 401:
            raise TkSessionExpired()
        if response.status_code != 200:
            raise TkApiError("电子保单下载HTTP状态异常")
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            client.request_guard()
            size += len(chunk)
            if size > MAX_PDF_BYTES * 4 // 3 + 65536:
                raise TkApiError("电子保单响应超过大小限制")
            chunks.append(chunk)
        try:
            payload = json.loads(b"".join(chunks))
        except (ValueError, UnicodeError):
            raise TkApiError("电子保单下载响应格式错误") from None
        client._check_expired(payload)
        client._require_success(payload, "电子保单下载")
        content = decode_policy_pdf(payload)
    return content, {
        "kind": policy["kind"],
        "referenceHash": hashlib.sha256(policy["subPolicyNo"].encode()).hexdigest(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "sizeBytes": len(content),
    }
