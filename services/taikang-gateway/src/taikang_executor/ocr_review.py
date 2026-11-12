"""Apply the frozen Java identity policy and explicit human edits to current OCR pages."""

import copy
import re
from datetime import date
from .supplier_evidence import identity_number


FIELD_TARGETS = {
    "licenseNo": ("DrivingLicense", "brandNo"),
    "vin": ("DrivingLicense", "VIN"),
    "engineNo": ("DrivingLicense", "engineNo"),
    "modelName": ("DrivingLicense", "brandModel"),
    "registrationDate": ("DrivingLicense", "regDate"),
    "issueDate": ("DrivingLicense", "issueDate"),
    "ownerName": ("DrivingLicense", "owner"),
    "idName": ("IdCard", "name"),
    "idNumber": ("IdCard", "id"),
    "certificateAddress": ("IdCard", "address"),
    "seatCount": ("DrivingLicense", "loadNumber"),
}


def apply_ocr_review(raw, anchor, edits, *, preserve_supplier_names=False, corrected_mass=False, unified_fields=False):
    pages = copy.deepcopy(raw)
    targets = dict(FIELD_TARGETS)
    if corrected_mass:
        targets.update(curbWeight=("DrivingLicense", "loadQualite"), loadWeight=("DrivingLicense", "curbWeight"))
    retained = set()
    if unified_fields:
        targets.update(
            licenseNoBack=("DrivingLicense", "brandNoBack"),
            vehicleAddress=("DrivingLicense", "address"),
            vehicleType=("DrivingLicense", "carType"),
            useNature=("DrivingLicense", "properties"),
            tractionWeight=("DrivingLicense", "pullWeight"),
            fuelType=("DrivingLicense", "fuelType"),
            sex=("IdCard", "sex"),
            nation=("IdCard", "nation"),
            birth=("IdCard", "birth"),
        )
        retained = {
            "ownerIdNumber",
            "ownerCertificateAddress",
            "applicantName",
            "applicantIdNumber",
            "applicantAddress",
            "phone",
            "email",
            "extraMaterialText",
            "unacceptedOptionalText",
            "unresolvedText",
            "unresolvedDates",
            "unresolvedNumericTokens",
            "inferredDateFields",
        }
    if not isinstance(edits, dict) or any(k not in set(targets) | {"name"} | retained for k in edits):
        raise ValueError("Unrecognized confirmed OCR edits")
    audit = {"manualFields": sorted(edits), "nameCorrected": False}
    for key, value in edits.items():
        if key in retained:
            audit.setdefault("additionalTextFields", {})[key] = value
            continue
        if not isinstance(value, str) or not value.strip() or len(value) > 700:
            raise ValueError("Invalid confirmed OCR field")
        if key == "name":
            if not preserve_supplier_names:
                pages["DrivingLicense"]["owner"] = value.strip()
            pages["IdCard"]["name"] = value.strip()
        else:
            group, field = targets[key]
            pages[group][field] = value.strip()
    car, card = pages["DrivingLicense"], pages["IdCard"]
    if (
        not preserve_supplier_names
        and isinstance(anchor, dict)
        and anchor.get("policyVersion") == "tk-document-identity-v1"
        and isinstance(anchor.get("name"), str)
        and anchor["name"].strip()
        and str(car.get("VIN") or car.get("vin") or "").strip().upper() == str(anchor.get("vin") or "").upper()
        and identity_number(card).strip().upper() == str(anchor.get("idNumber") or "").upper()
        and not set(edits) & {"name", "idName", "ownerName"}
    ):
        name = anchor["name"].strip()
        if str(car.get("owner") or "").strip() != name or str(card.get("name") or "").strip() != name:
            audit.update(
                {
                    "nameCorrected": True,
                    "nameBefore": {"owner": car.get("owner"), "person": card.get("name")},
                    "nameAfter": name,
                }
            )
            car["owner"] = card["name"] = name
    return pages, audit


def review_fields(pages):
    car, card = pages["DrivingLicense"], pages["IdCard"]
    fields = {key: str(pages[group].get(field) or "") for key, (group, field) in FIELD_TARGETS.items()}
    fields["idNumber"] = identity_number(card)
    fields["vin"] = str(car.get("VIN") or car.get("vin") or "")
    fields["licenseNo"] = str(car.get("brandNo") or car.get("brandNoBack") or "")
    fields["name"] = fields["idName"]
    return fields


def review_reason(pages):
    fields = review_fields(pages)
    labels = {
        "name": "姓名",
        "ownerName": "车主姓名",
        "idNumber": "身份证号",
        "vin": "车架号",
        "licenseNo": "车牌号",
        "engineNo": "发动机号",
        "modelName": "车辆型号",
        "registrationDate": "初登日期",
        "certificateAddress": "身份证地址",
    }
    missing = [label for key, label in labels.items() if not fields[key].strip()]
    if missing:
        return "泰康OCR缺少：" + "、".join(missing) + "，请引用本条消息补填。"
    if not re.fullmatch(r"[0-9]{17}[0-9Xx]", fields["idNumber"]):
        return "泰康OCR身份证号格式异常，请引用本条消息修改。"
    if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", fields["vin"].upper()):
        return "泰康OCR车架号格式异常，请引用本条消息修改。"
    digits = re.sub(r"\D", "", fields["registrationDate"])
    try:
        if len(digits) != 8:
            raise ValueError()
        date(int(digits[:4]), int(digits[4:6]), int(digits[6:]))
    except ValueError:
        return "泰康OCR初登日期异常，请引用本条消息修改。"
    if fields["ownerName"].strip() != fields["idName"].strip():
        return "行驶证车主与身份证姓名不一致，请核对原图并引用本条消息修改。"
    return None
