from taikang_executor.client import TkApiClient
from taikang_executor.staged_client import StagedTkClient


def test_verified_color_is_preserved_instead_of_forcing_other():
    assert TkApiClient._actual_color_code({"bodyColor": "灰色"}, {}) == "002"
    assert TkApiClient._actual_color_code({}, {"carInfoDto": {"bodyColor": "010"}}) == "010"
    assert TkApiClient._actual_color_code({}, {"carInfoVo": {"colorCode": "001"}}) == "001"
    assert TkApiClient._actual_color_code({}, {}) == "999"
    assert TkApiClient._actual_color_code({"bodyColor": "未识别"}, {}) == "999"


def test_quote_and_identity_regions_are_independent_and_address_is_preserved():
    client = StagedTkClient()
    try:
        client.apply_business_settings({
            "quoteArea": {"provinceCode": "530000", "provinceName": "云南省", "cityCode": "530100", "cityName": "昆明市"},
            "insuredArea": {"provinceCode": "530000", "provinceName": "云南省", "cityCode": "530400", "cityName": "玉溪市"},
        })
        client.com_code = "ACCOUNT-AREA"
        assert client._base_area_info("TEST-PLATE")["cityCode"] == "530100"
        fields = {"name": "测试投保人", "idNumber": "TEST-ID", "certificateAddress": "测试证件地址",
                  "birthDate": "1990-01-01", "sex": "2"}
        client.quote_context = {"ocr": {"name": fields["name"], "id_number": fields["idNumber"]},
                                "id_card": {"address": fields["certificateAddress"]}}
        result = client.build_confirmed_insure_info(fields, "13800000000")
        for role in ("appliInfo", "insuredInfo", "carOwnerVo"):
            assert result[role]["insuredCityCode"] == "530400"
            assert result[role]["insuredAddress"] == fields["certificateAddress"]
    finally:
        client.session.close()


def test_legacy_order_keeps_original_qujing_default():
    client = StagedTkClient()
    try:
        client.apply_business_settings(None)
        assert client.DEFAULT_CITY["code"] == "530300"
        assert client.insured_area["cityCode"] == "530300"
    finally:
        client.session.close()
