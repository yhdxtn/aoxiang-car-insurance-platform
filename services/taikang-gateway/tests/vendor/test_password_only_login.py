from unittest.mock import Mock, patch

import pytest

from taikang_executor.client import TkApiError, TkSessionExpired
from taikang_executor.staged_client import StagedTkClient, TkSupplierRejected, TkVerificationRequired


def test_staged_login_uses_fresh_password_request_and_never_captcha():
    client = StagedTkClient()
    calls = []

    def response(path, body, **kwargs):
        calls.append((path, body))
        if path.endswith("/login"):
            return {
                "status": "1",
                "data": {
                    "loginStatus": "0",
                    "tplatformId": "id",
                    "tplatLoginKey": "key",
                    "carssToken": "token",
                    "websysUserVo": {"fromid": "from", "websysUserAreaVos": [{"areacode": "0153"}]},
                },
            }
        return {"status": "1", "data": {"tkCarRequestToken": "request-token"}}

    try:
        with (
            patch.object(client.session, "get", return_value=Mock()),
            patch("taikang_executor.client.TkApiClient._post", side_effect=response),
            patch("taikang_executor.client.CaptchaRecognizer") as captcha,
        ):
            client.login("fixture-user", "fixture-password")
        captcha.assert_not_called()
        assert not any("Captcha" in p for p, _ in calls)
        request = next(b for p, b in calls if p.endswith("/login"))
        assert request["password"] != "fixture-password"
        assert client.from_id == "from" and client.com_code == "0153"
        assert sum(p.endswith("/login") for p, _ in calls) == 1
    finally:
        client.session.close()


@pytest.mark.parametrize("state", ["1", "2", "3"])
def test_verification_branch_stops_without_captcha_fallback(state):
    client = StagedTkClient()
    try:
        with (
            patch.object(client.session, "get", return_value=Mock()),
            patch(
                "taikang_executor.client.TkApiClient._post",
                side_effect=[
                    {"status": "1", "data": {"tkCarRequestToken": "test"}},
                    {"status": "1", "data": {"loginStatus": state}},
                ],
            ),
            patch("taikang_executor.client.CaptchaRecognizer") as captcha,
        ):
            with pytest.raises(TkVerificationRequired):
                client.login("fixture-user", "fixture-password")
        captcha.assert_not_called()
    finally:
        client.session.close()


def test_exact_expiry_is_distinct_from_business_rejection():
    client = StagedTkClient()
    try:
        with pytest.raises(TkSessionExpired):
            client._require_success({"status": "0", "message": "您的登录状态已过期，请重新登录！"}, "车型")
        with pytest.raises(TkSupplierRejected):
            client._require_success({"status": "0", "message": "业务评分高"}, "车型")
        with pytest.raises(TkApiError):
            client._require_success({"status": "0", "message": "未知异常"}, "车型")
    finally:
        client.session.close()
