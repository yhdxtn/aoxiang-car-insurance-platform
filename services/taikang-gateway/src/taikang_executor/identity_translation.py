"""Translate Java-selected roles into the captured 000012 contract, without selecting people."""

import copy
from .client import TkApiClient, TkApiError


def insure_info(client, roles, phone, email):
    if roles.get("policy") not in {"OWNER_INSURED_APPLICANT_V1", "OWNER_INSURED_APPLICANT_V2"} or roles.get(
        "needsRoleConfirmation"
    ):
        raise TkApiError("请确认本笔车主和投保人。")
    if roles != client.quote_context.get("identityRoles"):
        raise TkApiError("身份快照与原报价不一致")
    owner, applicant, insured = (copy.deepcopy(roles.get(key) or {}) for key in ("owner", "applicant", "insured"))
    if owner != insured:
        raise TkApiError("被保险人应为本笔车主")
    area = {
        "insuredProvinceCode": client.insured_area["provinceCode"],
        "insuredProvinceCname": client.insured_area["provinceName"],
        "insuredCityCode": client.insured_area["cityCode"],
        "insuredCityCname": client.insured_area["cityName"],
    }

    def person(value, label):
        for key, title in (("name", "姓名"), ("idNumber", "身份证号")):
            if not value.get(key):
                raise TkApiError("请补发" + label + title + "。")
        birth, sex = TkApiClient._id_birth_and_sex(value["idNumber"])
        # Explicit business contact for the original order; never borrowed from another person's OCR.
        return {
            **area,
            "insuredAddress": value.get("certificateAddress", ""),
            "insuredNature": "1",
            "birthday": birth,
            "identifyNumber": value["idNumber"],
            "identifyType": "01",
            "phoneNumber": phone,
            "sex": str(sex),
            "email": email,
            "isSelf": "1",
        }

    app = person(applicant, "投保人")
    own = person(owner, "车主")
    different = roles.get("differentApplicant") is True
    info = {
        "policyType": "1",
        "appliInfo": {
            **app,
            "appliName": applicant["name"],
            "withOwner": 0 if different else 1,
            "invoiceFlag": "1",
            "invoiceType": "002",
            "taxpayerType": "0",
            "taxNumber": applicant["idNumber"],
            "taxPayer": applicant["name"],
            "bank": "",
            "taxesPhone": "",
            "account": "",
            "taxRegistAddress": "",
            "serialno": 2,
        },
        "insuredInfo": {
            **own,
            "insuredName": owner["name"],
            "withOwner": 1,
            "withApplyer": 0 if different else 1,
            "serialno": 1,
        },
        "carOwnerVo": {
            **area,
            "insuredAddress": owner.get("certificateAddress", ""),
            "phoneNo": phone,
            "id": owner["idNumber"],
            "carOwnerNature": "1",
            "certificateType": "01",
            "name": owner["name"],
            "birthDate": own["birthday"],
            "sex": own["sex"],
        },
        "contacts": {"name": "", "identifyType": "", "identifyNumber": "", "phoneNumber": ""},
        "messageSendFlag": "0",
    }
    client._validate_insure_info(info)
    return info
