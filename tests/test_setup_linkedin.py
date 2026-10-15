import io
import json
import urllib.error
from urllib.parse import parse_qs, urlencode
from unittest.mock import MagicMock

import pytest

import setup_linkedin as setup


REDIRECT = "https://www.linkedin.com/developers/tools/oauth/redirect"
TEST_STATE = "test-state"
TEST_CLIENT_ID = "test-client-id"
TEST_CLIENT_SECRET = "test-client-secret"
TEST_ACCESS_TOKEN = "test-access-value"
TEST_SUBJECT = "test-member-id"


@pytest.fixture
def setup_context(tmp_path, monkeypatch):
    for name in ("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET", "LINKEDIN_REDIRECT_URI"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LINKEDIN_CLIENT_ID", TEST_CLIENT_ID)
    monkeypatch.setenv("LINKEDIN_CLIENT_SECRET", TEST_CLIENT_SECRET)
    monkeypatch.setattr(setup, "check_env_not_tracked", lambda: True)
    monkeypatch.setattr(setup, "ignored_output", lambda path: True)
    monkeypatch.setattr(setup, "load_dotenv", MagicMock())
    monkeypatch.setattr(setup.secrets, "token_urlsafe", lambda length: TEST_STATE)
    monkeypatch.setattr(setup.webbrowser, "open", MagicMock())
    callback = REDIRECT + "?" + urlencode({"code": "test-code", "state": TEST_STATE})
    monkeypatch.setattr(setup.getpass, "getpass", lambda prompt: callback)
    output = tmp_path / "credentials.out"
    requests = []

    def urlopen(request, timeout):
        requests.append((request, timeout))
        if request.full_url.endswith("/accessToken"):
            response = {"access_token": TEST_ACCESS_TOKEN, "expires_in": 5184000}
        else:
            assert request.full_url == "https://api.linkedin.com/v2/userinfo"
            assert request.get_header("Authorization") == f"Bearer {TEST_ACCESS_TOKEN}"
            response = {"sub": TEST_SUBJECT}
        return io.BytesIO(json.dumps(response).encode())

    monkeypatch.setattr(setup.urllib.request, "urlopen", urlopen)
    return output, requests, callback


def test_setup_uses_userinfo_and_saves_credentials_without_printing_them(setup_context, capsys):
    output, requests, _ = setup_context
    assert setup.main(["--no-browser", "--output", str(output)]) == 0
    assert len(requests) == 2
    assert all(timeout == 30 for _, timeout in requests)
    token_request = requests[0][0]
    assert token_request.get_method() == "POST"
    data = parse_qs(token_request.data.decode())
    assert data["client_id"] == [TEST_CLIENT_ID]
    assert data["client_secret"] == [TEST_CLIENT_SECRET]
    assert data["redirect_uri"] == [REDIRECT]
    values = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
    assert json.loads(values["LINKEDIN_ACCESS_TOKEN"]) == TEST_ACCESS_TOKEN
    assert json.loads(values["LINKEDIN_PERSON_URN"]) == f"urn:li:person:{TEST_SUBJECT}"
    captured = capsys.readouterr().out
    assert TEST_ACCESS_TOKEN not in captured
    assert TEST_CLIENT_SECRET not in captured
    assert TEST_SUBJECT not in captured
    assert "60 days" in captured
    setup.webbrowser.open.assert_not_called()


def test_setup_prompts_for_credentials_when_not_in_environment(setup_context, monkeypatch):
    output, _, callback = setup_context
    monkeypatch.delenv("LINKEDIN_CLIENT_ID")
    monkeypatch.delenv("LINKEDIN_CLIENT_SECRET")
    monkeypatch.setattr("builtins.input", lambda prompt: TEST_CLIENT_ID)
    monkeypatch.setattr(setup.getpass, "getpass", lambda prompt: TEST_CLIENT_SECRET if "Client Secret" in prompt else callback)
    assert setup.main(["--output", str(output)]) == 0
    setup.webbrowser.open.assert_called_once()


@pytest.mark.parametrize("expires_in", [5184000, "5184000"])
def test_expiry_accepts_integer_and_string_seconds(expires_in):
    message = setup.expiry_message(expires_in)
    assert "60 days" in message
    assert "UTC" in message


@pytest.mark.parametrize("expires_in", [None, "unknown", -1])
def test_unknown_expiry_has_renewal_guidance(expires_in):
    assert "about 60 days" in setup.expiry_message(expires_in)


@pytest.mark.parametrize("callback", [
    REDIRECT + "?code=test-code&state=wrong-state",
    REDIRECT + "?code=test-code",
    REDIRECT + "?state=test-state",
    REDIRECT + "?state=test-state&error=user_cancelled_authorize",
    REDIRECT + "?code=one&code=two&state=test-state",
    "https://example.com/callback?code=test-code&state=test-state",
    "test-code",
])
def test_invalid_callback_never_exchanges_code(setup_context, monkeypatch, callback):
    output, requests, _ = setup_context
    monkeypatch.setattr(setup.getpass, "getpass", lambda prompt: callback)
    assert setup.main(["--no-browser", "--output", str(output)]) == 1
    assert requests == []
    assert not output.exists()


@pytest.mark.parametrize("status", [401, 403, 500])
@pytest.mark.parametrize("failure_stage", ["token", "userinfo"])
def test_http_failure_does_not_echo_provider_response_or_credentials(setup_context, monkeypatch, capsys, status, failure_stage):
    output, _, _ = setup_context
    provider_detail = "sensitive-provider-detail"

    def fail(request, **kwargs):
        if failure_stage == "userinfo" and request.full_url.endswith("/accessToken"):
            return io.BytesIO(json.dumps({"access_token": TEST_ACCESS_TOKEN}).encode())
        raise urllib.error.HTTPError("https://api.linkedin.com", status, provider_detail, {}, io.BytesIO(TEST_ACCESS_TOKEN.encode()))

    monkeypatch.setattr(setup.urllib.request, "urlopen", fail)
    assert setup.main(["--no-browser", "--output", str(output)]) == 1
    captured = capsys.readouterr().out
    assert str(status) in captured
    assert TEST_ACCESS_TOKEN not in captured
    assert provider_detail not in captured
    assert not output.exists()


def test_tracked_environment_stops_setup_before_loading_or_authorizing(setup_context, monkeypatch):
    output, requests, _ = setup_context
    monkeypatch.setattr(setup, "check_env_not_tracked", lambda: False)
    assert setup.main(["--output", str(output)]) == 1
    setup.load_dotenv.assert_not_called()
    setup.webbrowser.open.assert_not_called()
    assert requests == []


def test_existing_output_is_never_overwritten(setup_context):
    output, requests, _ = setup_context
    output.write_text("keep existing data", encoding="utf-8")
    assert setup.main(["--output", str(output)]) == 1
    assert output.read_text(encoding="utf-8") == "keep existing data"
    assert requests == []


def test_unignored_output_is_rejected_before_authorization(setup_context, monkeypatch):
    output, requests, _ = setup_context
    monkeypatch.setattr(setup, "ignored_output", lambda path: False)
    assert setup.main(["--output", str(output)]) == 1
    assert not output.exists()
    assert requests == []


def test_missing_userinfo_subject_does_not_fall_back_to_old_endpoint(setup_context, monkeypatch):
    output, _, _ = setup_context
    request_json = MagicMock(side_effect=[{"access_token": TEST_ACCESS_TOKEN}, {}])
    monkeypatch.setattr(setup, "request_json", request_json)
    assert setup.main(["--no-browser", "--output", str(output)]) == 1
    assert request_json.call_count == 2
    assert request_json.call_args.args[0].full_url.endswith("/v2/userinfo")
    assert not output.exists()
