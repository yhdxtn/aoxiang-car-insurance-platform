import copy
import unittest

from taikang_executor.coverage_mapping import CoverageMappingError, map_coverage


def catalog(seats=5):
    return {
        "other": {"seats": seats},
        "flag": {"bzFlag": "0", "ciFlag": "1"},
        "bzKindVo": {"kindCode": "BZ", "isSelect": "0"},
        "ciKindsVo": [
            {
                "kindCode": code,
                "isSelect": "0",
                "amounts": [
                    {"amountEname": "2", "amountCname": "不投保"},
                    {"amountEname": amount, "amountCname": name},
                ],
            }
            for code, amount, name in [
                ("101", "25000", "车辆损失保额"),
                ("102", "2000000", "200万"),
                ("103", "10000", "1万"),
                ("104", "10000", "1万"),
                ("73", "100000", "10万"),
                ("78", "10000", "1万"),
                ("79", "10000", "1万"),
            ]
        ],
        "driverAccidentVo": {
            "carPlanInfoList": [
                {"planCode": "CARJCB0003", "sumPremium": "198"},
                {"planCode": "CARJCB0005", "sumPremium": "49"},
            ]
        },
    }


def selection():
    return dict(
        mode="FULL",
        vehicleLoss=True,
        thirdParty="2000000",
        driver="10000",
        passengerPerSeat="10000",
        medicalThirdParty="100000",
        medicalDriver="10000",
        medicalPassengerPerSeat="10000",
        nonCarIncluded=True,
        nonCarPlanCode="CARJCB0003",
    )


class CoverageMappingTest(unittest.TestCase):
    def test_third_party_accepts_catalog_without_unselected_vehicle_loss(self):
        original = catalog()
        original["ciKindsVo"] = [r for r in original["ciKindsVo"] if r["kindCode"] != "101"]
        before = copy.deepcopy(original)
        result = map_coverage(original, selection() | dict(mode="THIRD_PARTY", vehicleLoss=False), 5)
        self.assertNotIn("101", {r["kindCode"] for r in result["ciKindsVo"]})
        self.assertEqual(original, before)
        self.assertEqual(result["ciKindsVo"][0]["quoteAmount"], "2000000")
        with self.assertRaisesRegex(CoverageMappingError, "lacks vehicle loss"):
            map_coverage(original, selection(), 5)

    def test_only_vehicle_loss_changes_between_full_and_third_party(self):
        original = catalog()
        full = map_coverage(original, selection(), 5)
        changed = selection() | dict(mode="THIRD_PARTY", vehicleLoss=False)
        third = map_coverage(original, changed, 5)
        third["ciKindsVo"][0]["isSelect"] = "1"
        self.assertEqual(full, third)
        self.assertEqual(original, catalog())

    def test_valid_catalog_without_required_vehicle_loss_is_distinct_from_malformed_catalog(self):
        original = catalog()
        original["ciKindsVo"] = [row for row in original["ciKindsVo"] if row["kindCode"] != "101"]
        with self.assertRaises(CoverageMappingError) as missing:
            map_coverage(original, selection(), 5)
        self.assertEqual(type(missing.exception).__name__, "VehicleLossUnavailable")
        original["ciKindsVo"] = []
        with self.assertRaises(CoverageMappingError) as malformed:
            map_coverage(original, selection(), 5)
        self.assertNotEqual(type(malformed.exception).__name__, "VehicleLossUnavailable")

    def test_passenger_amount_is_per_seat_not_one_total_unit(self):
        result = map_coverage(catalog(7), selection(), 7)
        for row in result["ciKindsVo"]:
            if row["kindCode"] in {"104", "79"}:
                self.assertEqual(row["quoteAmount"], "60000")
                self.assertEqual(row["unitAmount"], "10000")
                self.assertEqual(row["quantity"], "6")

    def test_compulsory_plan_uses_only_java_supplied_noncar_selection(self):
        selected = {
            key: "0"
            for key in (
                "thirdParty",
                "driver",
                "passengerPerSeat",
                "medicalThirdParty",
                "medicalDriver",
                "medicalPassengerPerSeat",
            )
        }
        selected.update(mode="COMPULSORY", vehicleLoss=False, nonCarIncluded=True, nonCarPlanCode="CARJCB0005")
        result = map_coverage(catalog(6), selected, 6)
        self.assertEqual(result["ciKindsVo"], [])
        self.assertEqual(result["flag"]["ciFlag"], "0")
        self.assertEqual(result["driverAccidentVo"]["selectPlanCode"], "CARJCB0005")
        altered = catalog(6)
        altered["driverAccidentVo"]["carPlanInfoList"][1]["sumPremium"] = "59"
        with self.assertRaises(CoverageMappingError):
            map_coverage(altered, selected, 6)

    def test_unknown_limit_missing_product_and_medical_without_parent_fail_closed(self):
        invalid = [
            selection() | dict(thirdParty="3000000"),
            selection() | dict(nonCarPlanCode="unknown"),
            selection() | dict(driver="0", medicalDriver="10000"),
            selection() | dict(driver="NaN"),
        ]
        for choice in invalid:
            with self.assertRaises(CoverageMappingError):
                map_coverage(copy.deepcopy(catalog()), choice, 5)

    def test_supplier_seat_conflict_and_forced_noncar_on_five_seats_are_rejected(self):
        with self.assertRaises(CoverageMappingError):
            map_coverage(catalog(5), selection(), 7)
        single = {
            key: "0"
            for key in (
                "thirdParty",
                "driver",
                "passengerPerSeat",
                "medicalThirdParty",
                "medicalDriver",
                "medicalPassengerPerSeat",
            )
        }
        single.update(mode="COMPULSORY", vehicleLoss=False, nonCarIncluded=True, nonCarPlanCode="CARJCB0005")
        with self.assertRaises(CoverageMappingError):
            map_coverage(catalog(5), single, 5)


if __name__ == "__main__":
    unittest.main()
