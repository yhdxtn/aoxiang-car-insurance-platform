"""Supplier image evidence is stored separately from executable business fields."""

import re

POLICY = "PRIVATE_OCR_EVIDENCE_V1"
IMAGE_FIELDS = frozenset(
    {"Vehiclelicense", "Subvehiclelicense", "IdFront", "IdBack", "base64Imgs", "imgBase64", "imageBase64"}
)


def identity_number(card):
    primary = card.get("id")
    if primary not in (None, ""):
        return str(primary)
    alias = str(card.get("idCode") or "")
    return alias if re.fullmatch(r"[0-9]{17}[0-9Xx]", alias) else ""


def business_response(raw, evidence):
    """Keep unknown business fields. Strip only observed image-valued fields.

    The full immutable raw response must already have an authorized evidence
    reference. This is not a generic 'delete long strings' filter.
    """
    if not isinstance(evidence, dict) or not evidence.get("documentId"):
        raise ValueError("Verified raw OCR evidence is required")

    def clean(value):
        if isinstance(value, list):
            return [clean(v) for v in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            image = key in IMAGE_FIELDS or key == "idCode" and isinstance(item, str) and len(item) > 64
            if image and isinstance(item, (str, list)):
                result[key] = "" if isinstance(item, str) else []
            else:
                result[key] = clean(item)
        return result

    result = clean(raw)
    result["rawEvidence"] = dict(evidence)
    return result
