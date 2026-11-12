"""Verified product constraints; Java chooses and freezes the applicable rule."""

from decimal import Decimal

PRICES = {
    "CARJCB0001": Decimal("328"),
    "CARJCB0002": Decimal("268"),
    "CARJCB0003": Decimal("198"),
    "CARJCB0004": Decimal("98"),
    "CARJCB0005": Decimal("49"),
}


def validate_product(plan, seats, price=None):
    version = plan.get("nonCarPolicyVersion", 0)
    if isinstance(version, bool) or version not in (0, 1, 2):
        raise ValueError("Unsupported accident-product policy version")
    compulsory = plan.get("mode") == "COMPULSORY"
    selected = plan.get("nonCarIncluded")
    code = plan.get("nonCarPlanCode")
    if version == 0:
        if compulsory and (selected != (seats >= 6) or selected and code != "CARJCB0005"):
            raise ValueError("Compulsory non-car selection must follow the confirmed seat rule")
        if compulsory and selected and price is not None and price != Decimal("49"):
            raise ValueError("The confirmed 49-yuan product price changed; manual review required")
        return
    if version == 2 and not selected:
        if code is not None:
            raise ValueError("Unavailable accident selection cannot retain a selected product")
        return
    if not selected:
        if not compulsory or seats >= 6:
            raise ValueError("The frozen product rule requires an accident product")
        return
    allowed = {"CARJCB0004", "CARJCB0005"} if compulsory else {"CARJCB0001", "CARJCB0002", "CARJCB0003"}
    if code not in allowed:
        raise ValueError("Accident product does not match the confirmed insurance mode")
    if price is not None and price != PRICES[code]:
        raise ValueError("The confirmed accident product price changed; manual review required")
