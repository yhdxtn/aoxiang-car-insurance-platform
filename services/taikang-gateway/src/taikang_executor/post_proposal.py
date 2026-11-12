"""Same-order inspection continuation recovered from insurersInfo/orderManage JS.

Java owns commands, immutable material revisions and leases. No operation here
creates an order, repeats 000038, overrides quality failure, or signs a mandate.
"""

import base64
import copy
import hashlib
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

from taikang_executor.client import TkApiError, TkTransportError
from taikang_executor.staged_client import TkManualReview, TkOutcomeUnknown, TkSupplierRejected, business_feedback

REFERER = "https://car.tk.cn/offweb/views/page/insurersInfo/insurersInfo.html"
# Literal official zNodes. Requirement imageDetailCode is a DIFFERENT vocabulary;
# never guess a mapping or treat every directory as a mandatory photograph.
DIRECTORIES = {
    "01-12-01": "投保业务-核保资料-新增设备发票与清单",
    "01-12-02": "投保业务-核保资料-验车照片",
    "01-12-03": "投保业务-核保资料-已完成税减免税凭证",
    "01-12-04": "投保业务-核保资料-委托书",
    "01-14-01": "投保业务-证件照-证件照",
    "01-14-02": "投保业务-证件照-驾驶证",
    "01-14-03": "投保业务-证件照-人脸与身份证照",
    "01-15-01": "投保业务-车辆证件-行驶证",
    "01-15-02": "投保业务-车辆证件-购车发票",
    "01-15-03": "投保业务-车辆证件-合格证",
    "01-17-01": "投保业务-业务单证-投保单",
    "01-17-02": "投保业务-业务单证-免责事项说明书",
    "01-17-03": "投保业务-业务单证-浮动告知单",
    "01-18-01": "投保业务-其他资料-其他资料",
}


def begin_attempt(client, command_id, operation):
    client.post_proposal_progress = {
        "commandId": command_id,
        "operation": operation,
        "stage": "VALIDATING",
        "writeOutcome": "NOT_STARTED",
        "checkpointSequence": 0,
    }
    return client.post_proposal_progress


def _progress(client):
    value = getattr(client, "post_proposal_progress", None)
    return value if isinstance(value, dict) else None


def _checkpoint(client):
    callback = getattr(client, "post_proposal_checkpoint", None)
    if _progress(client) is not None and callable(callback):
        callback()


def _stage(client, name):
    if (progress := _progress(client)) is not None:
        progress["stage"] = name


def begin_write(client, name):
    # Fence before recording intent, and persist intent before any external
    # write. A lost checkpoint ACK never permits the supplier request.
    client.request_guard()
    progress = _progress(client)
    previous = progress.get("writeOutcome") if progress is not None else None
    if progress is not None:
        progress.update(stage=name, writeOutcome="IN_FLIGHT")
    try:
        _checkpoint(client)
    except Exception:
        # The supplier call has not started. A surviving leased worker can
        # prove that in its failure receipt. A lost process/lease still leaves
        # Java's persisted intent unknown, with no automatic recovery/replay.
        if progress is not None:
            progress["writeOutcome"] = previous
        raise


def confirm_write(client):
    if (progress := _progress(client)) is not None:
        progress["writeOutcome"] = "CONFIRMED"
    _checkpoint(client)


def failure_outcome(progress):
    return (
        "FAILED"
        if isinstance(progress, dict) and progress.get("writeOutcome") in {"NOT_STARTED", "CONFIRMED"}
        else "OUTCOME_UNKNOWN"
    )


def _identity(client):
    if not client._proposal_started or not client.order_id:
        raise TkManualReview("必须沿用已明确提交的原投保订单")
    proposal = client.proposal_result
    nested = proposal.get("data") if isinstance(proposal.get("data"), dict) else {}
    reference = nested.get("proposalNo") or proposal.get("proposalNo")
    if not isinstance(reference, str) or not reference.strip():
        raise TkOutcomeUnknown("原投保单号缺失，不能新建或重提投保")
    return reference


def _reply(client, state, **extra):
    inspection = client.inspection_context
    proposal = client.proposal_result
    requirements = inspection.get("requirements", proposal.get("checkCarSpecification") or [])
    reasons = business_feedback("验车/核保", inspection.get("page") or proposal)
    return {
        "postProposal": {
            "state": state,
            "orderId": client.order_id,
            "proposalNo": _identity(client),
            "requirements": requirements,
            "checkingCode": inspection.get("checkingCode"),
            "checkingCodeStatus": "AVAILABLE"
            if inspection.get("checkingCode")
            else inspection.get("checkingCodeStatus", "NOT_REQUESTED"),
            "checkingCodeIssue": inspection.get("checkingCodeIssue"),
            "checkingCodeFeedback": copy.deepcopy(inspection.get("checkingCodeFeedback", {})),
            "realTimeRequired": inspection.get("realTimeRequired", False),
            "autoSubmitInspection": str(
                (inspection.get("page") or proposal).get("checkCarFlag", proposal.get("checkCarFlag"))
            )
            == "1"
            and not inspection.get("submitStarted", False)
            and not inspection.get("realTimeRequired", False)
            and not inspection.get("outcomeUnknown", False)
            and bool(inspection.get("checkingCode")),
            "directories": [{"code": code, "name": name} for code, name in DIRECTORIES.items()],
            "uploaded": copy.deepcopy(inspection.get("uploaded", [])),
            "qualityFailures": copy.deepcopy(inspection.get("qualityFailures", [])),
            "supplierFeedback": reasons,
            **extra,
        }
    }


def _read_checking_code(client):
    """Optional display/challenge data: never lose an already-read checklist.

    Official carCheckingCode resolves outer status=1 without AES and the UI
    takes data.split('：')[1]. Do not guess encrypted or code-only variants.
    Authentication/lease failures still escape to their existing protections.
    """
    inspection = client.inspection_context
    inspection["checkingCodeStatus"] = "UNAVAILABLE"
    inspection.pop("checkingCodeFeedback", None)
    inspection.pop("checkingCodeIssue", None)
    try:
        raw = client._post(
            "/rest/controller/entrance",
            {"channelCode": client.CHANNEL, "orderID": client.order_id},
            referer=REFERER,
            action_type="000133",
        )
        client._require_success(raw, "读取本单验车码")
    except TkSupplierRejected as error:
        inspection["checkingCodeIssue"] = "SUPPLIER_REJECTED"
        inspection["checkingCodeFeedback"] = error.supplier_feedback
        return
    except TkTransportError as error:
        # Preserve the established account-cache HTTP401 logout handling.
        if error.transport_diagnostic.get("httpStatus") == 401:
            raise
        if isinstance(error.__cause__, (requests.ConnectionError, requests.Timeout)):
            client.reset_transport_pool()
        inspection["checkingCodeIssue"] = "CONNECTION_ERROR"
        return
    value = raw.get("data")
    parts = value.split("：") if isinstance(value, str) else []
    if (
        len(parts) != 2
        or not parts[0].strip()
        or not 0 < len(parts[1].strip()) <= 200
        or any(ord(char) < 32 or ord(char) == 127 for char in parts[1])
    ):
        inspection["checkingCodeIssue"] = "RESPONSE_INVALID"
        return
    inspection["checkingCode"] = parts[1].strip()
    inspection["checkingCodeStatus"] = "AVAILABLE"


def inspect_order(client, *, refresh_checking_code=False):
    """One on-demand read, never an idle audit polling loop."""
    _identity(client)
    _stage(client, "STATUS_READ")
    page = client.decode_success(
        client._post(
            "/rest/controller/entrance",
            {
                "orderID": client.order_id,
                "fromId": client.from_id,
                "channelCode": client.CHANNEL,
                "previousStep": "080000",
            },
            referer=REFERER,
            action_type="000021",
        ),
        "读取本单验车/核保状态",
    )
    # Only this existing, verified auto-underwriting branch permits payment.
    # submit's underWriteFlag=2 is NOT approval or a policy issuance fact.
    for key in ("orderId", "orderID"):
        if page.get(key) is not None and page[key] != client.order_id:
            raise TkManualReview("验车状态返回了其他订单，已停止续办")
    client.underwriting_result = copy.deepcopy(page)
    inspection = client.inspection_context
    inspection["page"] = copy.deepcopy(page)
    inspection["realTimeRequired"] = str(page.get("canclePhotoFlag")) == "1"
    requirements = page.get("checkCarSpecification")
    if isinstance(requirements, list):
        inspection["requirements"] = copy.deepcopy(requirements)
    unresolved_write = inspection.get("outcomeUnknown") or (
        inspection.get("submitStarted") and not inspection.get("submitResult")
    )
    if (
        str(page.get("underWriteFlag")) == "3"
        and str(page.get("checkCarFlag")) != "1"
        and not unresolved_write
        and not inspection["realTimeRequired"]
    ):
        inspection["underwritingApproved"] = True
        return None
    inspection["underwritingApproved"] = False
    if str(page.get("checkCarFlag", client.proposal_result.get("checkCarFlag"))) == "1":
        if (
            not inspection.get("checkingCode")
            and not inspection.get("submitStarted")
            and not inspection.get("outcomeUnknown")
            and (refresh_checking_code or inspection.get("checkingCodeStatus") != "UNAVAILABLE")
        ):
            _read_checking_code(client)
        state = "REALTIME_REQUIRED" if inspection["realTimeRequired"] else "MATERIALS_REQUIRED"
    else:
        state = "WAITING_REVIEW"
    if inspection.get("submitStarted") and inspection.get("submitResult"):
        state = "WAITING_REVIEW"
    if inspection.get("qualityFailures"):
        state = "QUALITY_REJECTED"
    if inspection["realTimeRequired"]:
        state = "REALTIME_REQUIRED"
    if inspection.get("outcomeUnknown") or (inspection.get("submitStarted") and not inspection.get("submitResult")):
        state = "SUBMISSION_UNKNOWN"
    return _reply(client, state)


def _file(client, path, directory, command_id, index):
    content = Path(path).read_bytes()
    if not 0 < len(content) <= 15 * 1024 * 1024:
        raise TkApiError("验车图片大小无效")
    # Validate the exact bytes that will be sent; never reread or transcode them.
    # Phone JPEGs with an MPF container are reported as MPO by Pillow.
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format not in {"JPEG", "MPO", "PNG"}:
                raise TkApiError("验车仅接收原始JPEG或PNG图片")
            if not 0 < image.width * image.height <= 40_000_000:
                raise TkApiError("验车图片分辨率超过处理上限")
            suffix, mime = ("png", "image/png") if image.format == "PNG" else ("jpg", "image/jpeg")
            image.verify()
        with Image.open(BytesIO(content)) as image:
            image.seek(0)
            image.load()  # Primary frame must decode; verify() alone is insufficient.
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise TkApiError("验车图片解码失败，请补发对应证件原图") from exc
    reference = _identity(client)
    only_id = f"{directory}-{command_id}-{index}"
    filename = f"{reference}{directory}{index}.{suffix}"
    return {
        "fullProposalNo": reference,
        "typePath": directory,
        "shootCity": "",
        "shootProvince": "",
        "uploadType": "1",
        "fileType": "1fileOrgName" + only_id,
        "channelCode": client.CHANNEL,
        "onlyId": only_id,
        "base64FileName": filename,
        "base64File": f"data:{mime};base64," + base64.b64encode(content).decode("ascii"),
    }, hashlib.sha256(content).hexdigest()


def upload_and_continue(client, paths, directory, command_id, replacement_file_id=None):
    if directory not in DIRECTORIES or not 1 <= len(paths) <= 4:
        raise TkApiError("需要明确选择本单影像目录，每次一至四张原图")
    inspection = client.inspection_context
    pending = inspect_order(client)
    resumed_upload = inspection.pop("resumeConfirmedUpload", None)
    if pending is None:
        # Already approved: no stale photographs are uploaded to the approved order.
        return None
    if pending["postProposal"]["state"] in {"REALTIME_REQUIRED", "SUBMISSION_UNKNOWN"}:
        return pending
    if not permitted_document_operation(client, pending):
        return pending
    _stage(client, "VALIDATING")
    parameters, digests, seen = [], [], set()
    for index, path in enumerate(paths):
        item, digest = _file(client, path, directory, command_id, index)
        if digest in seen:
            continue
        seen.add(digest)
        # Exact known original in same category must not be uploaded again.
        if any(
            row.get("sha256") == digest and row.get("directory") == directory for row in inspection.get("uploaded", [])
        ):
            continue
        parameters.append(item)
        digests.append(digest)
    if resumed_upload and parameters:
        raise TkManualReview("已确认上传的原图与续办资料不一致，请核对原单")
    if not parameters:
        if resumed_upload and pending["postProposal"]["autoSubmitInspection"]:
            return submit_and_continue(client)
        return _reply(client, pending["postProposal"]["state"], note="这些原图已上传，本次未重复上传或提交验车。")
    previous_failures = [row for row in inspection.get("qualityFailures", []) if row["directory"] == directory]
    replacement = next((row for row in previous_failures if row["fileId"] == replacement_file_id), None)
    if replacement_file_id is None and len(previous_failures) == len(parameters) == 1:
        replacement = previous_failures[0]
    if replacement_file_id is not None and replacement is None:
        raise TkManualReview("要替换的照片已变化，请使用本单最新待办的失败编号")
    if previous_failures and (replacement is None or len(parameters) != 1):
        raise TkManualReview("同目录多张失败时请明确选择一个失败编号，每次发送一张补拍原图")
    if replacement and replacement.get("sha256") == digests[0]:
        return _reply(client, "QUALITY_REJECTED", note="这张原图仍为质检失败，请补拍新图；原失败记录保留。")
    if replacement:
        # Fresh replacement photographs are an explicit reupload action; never
        # choose the UI's DIRECT_UPLOAD override for a failed quality result.
        begin_write(client, "QUALITY_REUPLOAD")
        client._require_success(
            client._post(
                "/carCheck/qualityCheck/userAction",
                {
                    "fileIdList": [replacement["fileId"]],
                    "fullProposalNo": _identity(client),
                    "userAction": "REUPLOAD",
                },
                referer=REFERER,
            ),
            "登记本单补拍",
        )
        confirm_write(client)
    begin_write(client, "QUALITY_UPLOAD")
    raw = client._post("/carCheck/qualityVerifyImg", parameters, referer=REFERER)
    client._require_success(raw, "影像质检")
    rows = raw.get("data")
    # Retain every unambiguous file even if another receipt is absent/broken.
    # Neither an unmatched name nor a reused fileId may establish an upload.
    rows = rows if isinstance(rows, list) else []
    names = [
        row["base64FileName"] for row in rows if isinstance(row, dict) and isinstance(row.get("base64FileName"), str)
    ]
    file_ids = [str(row["fileId"]) for row in rows if isinstance(row, dict) and row.get("fileId")]
    matches = {
        row["base64FileName"]: row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("base64FileName"), str)
    }
    expected_names = {item["base64FileName"] for item in parameters}
    incomplete = len(rows) != len(parameters) or set(names) != expected_names
    inspection.setdefault("uploaded", [])
    inspection.setdefault("qualityFailures", [])
    for item, digest in zip(parameters, digests, strict=True):
        name = item["base64FileName"]
        row = matches.get(name, {})
        file_id = row.get("fileId")
        if (
            names.count(name) != 1
            or not isinstance(file_id, (str, int))
            or isinstance(file_id, bool)
            or not file_id
            or isinstance(file_id, str)
            and not file_id.strip()
            or file_ids.count(str(file_id)) != 1
            or not isinstance(row.get("typeCheck"), bool)
            or (row["typeCheck"] and not isinstance(row.get("verifyInfo"), bool))
        ):
            incomplete = True
            continue
        accepted_row = {"directory": directory, "fileId": str(row["fileId"]), "sha256": digest}
        if replacement:
            accepted_row["replacesFileId"] = replacement["fileId"]
            inspection.setdefault("qualityHistory", []).append(copy.deepcopy(replacement))
            inspection["qualityFailures"] = [
                old for old in inspection.get("qualityFailures", []) if old["fileId"] != replacement["fileId"]
            ]
        if row.get("typeCheck") and not row.get("verifyInfo"):
            inspection.setdefault("qualityFailures", []).append(
                {**accepted_row, "reasons": row.get("verifyResultList") or []}
            )
        else:
            inspection.setdefault("uploaded", []).append(accepted_row)
        _checkpoint(client)
    # qualityVerifyImg stores successful images and returns their actual fileId.
    # Official uploadImgFun only records these IDs; it does NOT reupload them via
    # upload/file or uploadImage before validateCarAIResult/validateCarSubmit.
    if incomplete:
        raise TkOutcomeUnknown("部分质检回执不完整，已保存明确返回的文件；其余待核实，禁止整批重传")
    confirm_write(client)
    if inspection.get("qualityFailures"):
        return _reply(client, "QUALITY_REJECTED")
    if pending["postProposal"]["autoSubmitInspection"]:
        return submit_and_continue(client)
    # Official btnUpload closes the image panel without carCheck/submit outside
    # an outstanding inspection. Quality has already stored the image; an
    # ordinary underwriting supplement must never become another inspection.
    return inspect_order(client)


def submit_and_continue(client):
    reference = _identity(client)
    inspection = client.inspection_context
    pending = inspect_order(client)
    if pending is None:
        return None
    if not permitted_document_operation(client, pending):
        return pending
    if pending["postProposal"]["state"] in {"REALTIME_REQUIRED", "SUBMISSION_UNKNOWN", "WAITING_REVIEW"}:
        return pending
    if inspection.get("submitStarted"):
        return _reply(client, "WAITING_REVIEW")
    if inspection.get("qualityFailures"):
        # A later successful replacement removes only its own category's failure.
        return _reply(client, "QUALITY_REJECTED", qualityFailures=inspection["qualityFailures"])
    if not pending["postProposal"]["autoSubmitInspection"]:
        # Missing challenge information must not prevent document association,
        # but cannot authorize an inspection submission. Only explicit CHECK
        # may try to retrieve it again; never fetch it in a nested upload/read.
        return pending
    file_ids = list(dict.fromkeys(row["fileId"] for row in inspection.get("uploaded", [])))
    if not file_ids:
        return _reply(client, "MATERIALS_REQUIRED")
    try:
        _stage(client, "AI_READ")
        raw = client._post(
            "/carCheck/AIResult/query",
            {"fullProposalNo": reference, "channelCode": client.CHANNEL, "fieldIds": file_ids},
            referer=REFERER,
        )
        client._require_success(raw, "验车智能核验")
    except TkSupplierRejected as error:
        return _reply(client, "MATERIALS_REQUIRED", supplierFeedback=error.supplier_feedback)
    # The legacy wrapper checks outer status, decrypts JSON(data).data and then
    # lets the UI continue. Preserve the exact framing; do not interpret a
    # guessed inner approval code or the original quote statuses 4/10 here.
    encrypted = client.decrypt_business_data(raw.get("data"))
    if not isinstance(encrypted, dict) or not isinstance(encrypted.get("data"), str):
        raise TkManualReview("智能核验返回与官方解密合同不符")
    inspection["aiResult"] = client.decrypt_business_data(encrypted["data"])
    begin_write(client, "INSPECTION_SUBMIT")
    inspection["submitStarted"] = True
    result = client._post(
        "/carCheck/submit",
        {
            "fullProposalNo": reference,
            "channelCode": client.CHANNEL,
            "orderType": "1",
            "formId": client.from_id,
            "tplatformId": client.tplatform_id,
            "fieldIds": ["1"],
        },
        referer=REFERER,
    )
    client._require_success(result, "提交本单验车")
    if not isinstance(result.get("data"), dict):
        raise TkOutcomeUnknown("验车已提交但回执不完整，禁止重复提交")
    inspection["submitResult"] = copy.deepcopy(result)
    confirm_write(client)
    # A single fresh underwriting read after the accepted submission. Pending
    # review persists until an explicit query/event; never periodically resubmit.
    return inspect_order(client)


def permitted_document_operation(client, pending):
    """Execute Java's frozen scope only; changed supplier facts return to Java."""
    mode = getattr(client, "post_proposal_mode", None)
    if mode is None:
        return True  # Frozen legacy commands retain their own protocol.
    if mode != "DOCUMENT_SUPPLEMENT":
        return False
    expected = getattr(client, "post_proposal_scope_requirements", None)
    return isinstance(expected, list) and expected == pending["postProposal"].get("requirements")
