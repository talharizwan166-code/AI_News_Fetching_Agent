import re
import runpy
import textwrap
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src import linkedin_poster as poster


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch):
    monkeypatch.setattr(poster, "LINKEDIN_ACCESS_TOKEN", "test-access-value")
    monkeypatch.setattr(poster, "LINKEDIN_PERSON_URN", "urn:li:person:test-member")


@pytest.mark.parametrize("override, expected", [(None, "202610"), ("202609", "202609")])
def test_linkedin_version_header_uses_environment_or_verified_default(monkeypatch, override, expected):
    if override is None:
        monkeypatch.delenv("LINKEDIN_API_VERSION", raising=False)
    else:
        monkeypatch.setenv("LINKEDIN_API_VERSION", override)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: None)
    config = runpy.run_path(str(ROOT / "src/config.py"))
    assert config["LINKEDIN_API_VERSION"] == expected
    monkeypatch.setattr(poster, "LINKEDIN_API_VERSION", config["LINKEDIN_API_VERSION"])
    request = MagicMock()
    request.return_value.__enter__.return_value.status = 201
    monkeypatch.setattr(poster.urllib.request, "urlopen", request)
    poster.post_to_linkedin("Example post")
    sent = request.call_args.args[0]
    assert sent.get_header("Linkedin-version") == expected
    assert sent.get_method() == "POST"
    assert request.call_args.kwargs["timeout"] == 30


@pytest.mark.parametrize("status", [401, 426, 403])
def test_publish_errors_preserve_status_without_reading_private_response_body(monkeypatch, caplog, status):
    body = MagicMock()
    error = urllib.error.HTTPError("https://api.linkedin.com/rest/posts", status, "Private details", {}, body)
    monkeypatch.setattr(poster.urllib.request, "urlopen", MagicMock(side_effect=error))
    error_type = poster.LinkedInAPIError if status in (401, 426) else urllib.error.HTTPError
    with pytest.raises(error_type) as caught:
        poster.post_to_linkedin("Example post")
    if status in (401, 426):
        assert caught.value.status_code == status
        assert str(status) in str(caught.value)
    if status == 401:
        assert "Renew authorization" in str(caught.value)
    if status == 426:
        assert "LINKEDIN_API_VERSION" in str(caught.value)
    body.read.assert_not_called()
    assert "Private details" not in caplog.text


def test_workflow_repository_variable_fallback_matches_config_default(monkeypatch):
    monkeypatch.delenv("LINKEDIN_API_VERSION", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: None)
    config = runpy.run_path(str(ROOT / "src/config.py"))
    workflow = (ROOT / ".github/workflows/linkedin_approve.yml").read_text(encoding="utf-8")
    assert "vars.LINKEDIN_API_VERSION || '" + config["LINKEDIN_API_VERSION"] + "'" in workflow


@pytest.mark.parametrize("status, expected", [(401, "token_expired"), (426, "version_sunset"), (403, "other")])
def test_actual_workflow_post_step_classifies_publish_failures(tmp_path, monkeypatch, status, expected):
    workflow = (ROOT / ".github/workflows/linkedin_approve.yml").read_text(encoding="utf-8")
    step = workflow.split("      - name: Post to LinkedIn\n", 1)[1].split("      - name: Comment and close", 1)[0]
    match = re.search(r'^          python -c "\n(.*?)^          "\s*$', step, re.M | re.S)
    assert match is not None
    script = textwrap.dedent(match.group(1))
    output = tmp_path / "workflow.outputs"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("ISSUE_BODY", "<!-- POST_START -->Example post<!-- POST_END -->\n<!-- ARTICLE_URL:https://example.com/article -->")
    error = poster.LinkedInAPIError(status, "Test publish failure")
    publish = MagicMock(side_effect=error)
    monkeypatch.setattr(poster, "post_to_linkedin", publish)
    with pytest.raises(SystemExit) as caught:
        exec(compile(script, "workflow-post", "exec"), {})
    assert caught.value.code == 1
    publish.assert_called_once()
    assert output.read_text(encoding="utf-8") == f"failure_type={expected}\n"
