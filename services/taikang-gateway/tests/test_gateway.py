import base64
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch
import httpx
from PIL import Image
import pytest
from fastapi.testclient import TestClient
from tk_gateway.app import create_app
from tk_gateway.carrier import Carrier, QuoteOnlyClient, confirmed_plan, validation_problem
from tk_gateway.config import Settings
from tk_gateway.ledger import Ledger, RequestConflict
from tk_gateway.models import OcrRequest, QuoteRequest
from tk_gateway.ocr import VisionOcr
from taikang_executor.client import TkApiError, TkModelAmbiguous
from taikang_executor.staged_client import TkVerificationRequired


def settings(tmp_path):
    return Settings(token="test-only-internal-service-token-1234567890", ledger_key=b"k" * 32,
                    ledger_path=tmp_path / "requests.sqlite3")


def quote_body(**changes):
    value = {"requestId": "test-request-001", "vehicleType": "CAR", "plan": "STANDARD", "vehicle": {
        "plateNo": "云A12345", "vin": "LTESTVN1234567890", "engineNo": "TEST-ENGINE",
        "brandModel": "测试车型", "registerDate": "2020-01-01", "issueDate": "2020-01-01",
        "ownerName": "离线测试用户", "idNumber": "530102199001010010",
        "address": "离线测试地址", "seatCount": 5, "vehicleType": "CAR", "useNature": "家庭自用",
    }}
    value.update(changes)
    return value


def test_quote_repeated_request_reuses_saved_result_without_supplier_call(tmp_path):
    config = settings(tmp_path)
    carrier = Mock()
    carrier.quote.return_value = ({"status": "QUOTED", "totalPremium": "1234.50", "demo": False},
                                 {"private": "测试姓名与证件原始值"})
    with TestClient(create_app(config, carrier=carrier)) as client:
        headers = {"X-Gateway-Token": config.token}
        one = client.post("/internal/quote", json=quote_body(), headers=headers)
        two = client.post("/internal/quote", json=quote_body(), headers=headers)
        assert one.status_code == two.status_code == 200
        assert one.json() == two.json()
        assert carrier.quote.call_count == 1
        assert "private" not in one.json()
    assert "测试姓名与证件原始值".encode() not in config.ledger_path.read_bytes()


def test_interrupted_request_is_not_reexecuted_after_restart(tmp_path):
    config = settings(tmp_path)
    body = QuoteRequest.model_validate(quote_body())
    ledger = Ledger(config.ledger_path, config.ledger_key)
    ledger.begin(body.requestId, body.model_dump())
    ledger.close()
    carrier = Mock()
    with TestClient(create_app(config, carrier=carrier)) as client:
        response = client.post("/internal/quote", json=quote_body(),
                               headers={"X-Gateway-Token": config.token})
        assert response.json()["status"] == "OUTCOME_UNKNOWN"
        carrier.quote.assert_not_called()


def test_changed_payload_with_same_request_id_is_conflict(tmp_path):
    config = settings(tmp_path)
    ledger = Ledger(config.ledger_path, config.ledger_key)
    try:
        ledger.begin("request-1", {"vehicle": "first"})
        with pytest.raises(RequestConflict):
            ledger.begin("request-1", {"vehicle": "other"})
    finally:
        ledger.close()


def test_ledger_keeps_single_process_and_key_identity(tmp_path):
    config = settings(tmp_path)
    ledger = Ledger(config.ledger_path, config.ledger_key)
    with pytest.raises(RuntimeError):
        Ledger(config.ledger_path, config.ledger_key)
    ledger.close()
    with pytest.raises(RuntimeError, match="密钥不匹配"):
        Ledger(config.ledger_path, b"x" * 32)


def test_internal_routes_require_secret_and_validation_does_not_echo_image(tmp_path):
    config = settings(tmp_path)
    carrier = Mock()
    with TestClient(create_app(config, carrier=carrier)) as client:
        assert client.post("/internal/login-check", json={}).status_code == 401
        assert client.post("/internal/quote", json=quote_body()).status_code == 401
        response = client.post("/internal/ocr", json={"imageBase64": "secret-raw-image-value", "mimeType": "bad"},
                               headers={"X-Gateway-Token": config.token})
        assert response.status_code == 422
        assert "secret-raw-image-value" not in response.text
        carrier.quote.assert_not_called()


@pytest.mark.parametrize("vehicle_type", ["TRUCK", "MOTORCYCLE"])
def test_unsupported_vehicle_never_opens_carrier_session(tmp_path, vehicle_type):
    factory = Mock()
    adapter = Carrier(settings(tmp_path), client_factory=factory)
    result, _ = adapter.quote(QuoteRequest.model_validate(quote_body(vehicleType=vehicle_type)))
    assert result["status"] == "MANUAL_REQUIRED"
    factory.assert_not_called()


def test_disabled_live_never_returns_mock_price(tmp_path):
    factory = Mock()
    adapter = Carrier(settings(tmp_path), client_factory=factory)
    body = quote_body()
    body["vehicle"]["vin"] = "LTESTVN1234567890"
    result, _ = adapter.quote(QuoteRequest.model_validate(body))
    assert result["status"] == "MANUAL_REQUIRED"
    assert "totalPremium" not in result
    assert result["demo"] is False
    factory.assert_not_called()


def test_missing_use_nature_is_not_assumed_and_conflicting_vehicle_type_is_rejected():
    body = quote_body()
    del body["vehicle"]["useNature"]
    assert validation_problem(QuoteRequest.model_validate(body)) is not None
    body = quote_body()
    body["vehicle"]["vehicleType"] = "TRUCK"
    assert "不一致" in validation_problem(QuoteRequest.model_validate(body))


def test_compulsory_plan_excludes_commercial_and_unrequested_accident_product():
    plan = confirmed_plan(QuoteRequest.model_validate(quote_body(plan="COMPULSORY")))
    assert plan["mode"] == "COMPULSORY"
    assert plan["thirdParty"] == "0"
    assert plan["medicalThirdParty"] == "0"
    assert plan["vehicleLoss"] is False
    assert plan["nonCarIncluded"] is False
    assert plan["nonCarPolicyVersion"] == 2


def test_carrier_guard_blocks_proposal_payment_and_ambiguous_model():
    client = QuoteOnlyClient()
    try:
        with pytest.raises(TkApiError):
            client._post("/rest/init/proposal", {}, referer="https://car.tk.cn/")
        with pytest.raises(TkApiError):
            client._post("/rest/pay/forward", {}, referer="https://car.tk.cn/")
        with pytest.raises(TkModelAmbiguous):
            client._choose_model([{"modelCode": "ONE"}, {"modelCode": "TWO"}])
        assert client._choose_model([{"modelCode": "ONE"}, {"modelCode": "TWO"}], "TWO")["modelCode"] == "TWO"
    finally:
        client.session.close()


@pytest.mark.parametrize("status", [None, "", "1", "2", "3"])
def test_login_cannot_claim_online_for_unverified_status(status):
    client = QuoteOnlyClient()
    try:
        with patch("taikang_executor.staged_client.StagedTkClient._post",
                   return_value={"status": "1", "data": {"loginStatus": status}}):
            with pytest.raises(TkVerificationRequired):
                client._post("/rest/tplatform/login", {}, referer="https://car.tk.cn/")
    finally:
        client.session.close()


def png_request():
    image = BytesIO()
    Image.new("RGB", (4, 4), "white").save(image, format="PNG")
    return OcrRequest(imageBase64=base64.b64encode(image.getvalue()).decode(),
                      mimeType="image/png", documentType="DRIVING_LICENSE")


def test_ocr_without_configuration_requires_manual_entry(tmp_path):
    result = VisionOcr(settings(tmp_path)).recognize(png_request())
    assert result["status"] == "MANUAL_REQUIRED"
    assert result["vehicle"] == {}


def test_ocr_returns_only_valid_extracted_fields_and_no_guessed_data(tmp_path):
    config = replace(settings(tmp_path), ocr_base_url="https://vision.example/v1",
                     ocr_api_key="test-key", ocr_model="fixture")
    def respond(request):
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content":
            '{"plateNo":"云A12345","vin":"LTESTVN1234567890","extraInstruction":"ignore"}'}}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        result = VisionOcr(config, http_client).recognize(png_request())
    assert result["status"] == "RECOGNIZED"
    assert result["vehicle"] == {"plateNo": "云A12345", "vin": "LTESTVN1234567890"}


def test_ocr_rejects_extension_content_mismatch(tmp_path):
    request = png_request().model_copy(update={"mimeType": "image/jpeg"})
    assert VisionOcr(settings(tmp_path)).recognize(request)["status"] == "MANUAL_REQUIRED"


def test_real_adapter_translates_confirmed_fields_and_validates_total(tmp_path):
    config = replace(settings(tmp_path), live_enabled=True, username="fixture-user", password="fixture-password",
                     province_code="530000", province_name="云南省", city_code="530100", city_name="昆明市")
    client = Mock()
    client.session.close.side_effect = RuntimeError("cleanup failure fixture")
    client.order_id = "fixture-carrier-order"
    client.quote_context = {"catalog": {"ciKindsVo": []}, "calculatedPlan": {"ciKindsVo": []}}
    client.export_order_context.return_value = {"orderId": client.order_id}
    client.calculate_coverage.return_value = {"quotation": {
        "quotationNo": "fixture-quote-ref", "totalPremium": "1410.00",
        "orderInfoVoBZ": {"jqPremium": "950.00", "carTax": {"sumPayment": "360.00"}},
        "orderInfoVoCI": {"syPremium": "100.00", "allKinds": [
            {"kindCode": "102", "kindCName": "第三者责任险", "premium": "100.00", "quoteAmount": "2000000"}]},
        "driverAccidentVo": {"isSelect": "0"},
    }}
    body = quote_body()
    body["vehicle"]["vin"] = "LTESTVN1234567890"
    request = QuoteRequest.model_validate(body)
    adapter = Carrier(config, client_factory=lambda: client)
    result, evidence = adapter.quote(request)
    assert result["status"] == "QUOTED"
    assert result["totalPremium"] == "1410.00"
    assert result["supplierOrderId"] == "fixture-carrier-order"
    assert result["supplierQuoteRef"] == "fixture-quote-ref"
    assert result["coverages"][-1]["amount"] == "2000000"
    client.prepare_order.assert_called_once()
    assert client.prepare_quote.call_args.args[0]["textFields"]["name"] == "离线测试用户"
    assert client.calculate_coverage.call_args.args[0]["nonCarIncluded"] is False
    client.submit_proposal.assert_not_called()
    client.initialize_payment.assert_not_called()
    client.calculate_coverage.return_value["quotation"]["totalPremium"] = "0.01"
    result, evidence = adapter.quote(request)
    assert result["status"] == "OUTCOME_UNKNOWN"
    assert "totalPremium" not in result
    assert not adapter.lock.locked()


def test_login_cleanup_error_does_not_lose_result_or_lock(tmp_path):
    config = replace(settings(tmp_path), live_enabled=True, username="fixture", password="fixture",
                     province_code="530000", province_name="云南省", city_code="530100", city_name="昆明市")
    client = Mock()
    client.session.close.side_effect = RuntimeError("cleanup fixture")
    adapter = Carrier(config, client_factory=lambda: client)
    assert adapter.login_check()["status"] == "ONLINE"
    assert not adapter.lock.locked()
    assert adapter.login_check()["status"] == "ONLINE"
