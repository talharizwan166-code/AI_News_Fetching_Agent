from unittest.mock import patch, MagicMock
import pytest
from google.genai.errors import ServerError
from src.fetcher import Article
from src.generator import generate_linkedin_post


def _article():
    return Article(
        title="OpenAI Launches GPT-5",
        url="https://example.com/gpt5",
        source="TechCrunch AI",
        summary="OpenAI announced GPT-5 with improved reasoning capabilities.",
    )


def _server_error():
    resp = MagicMock()
    resp.status_code = 503
    resp.json.return_value = {"error": {"message": "UNAVAILABLE"}}
    return ServerError(503, {"error": {"message": "UNAVAILABLE"}}, resp)


@patch("src.generator.GEMINI_API_KEY", "fake-key")
@patch("src.generator.genai")
def test_generate_returns_post(mock_genai):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Here is a LinkedIn post about GPT-5. #AI #OpenAI"
    mock_client.models.generate_content.return_value = mock_response
    mock_genai.Client.return_value = mock_client

    post = generate_linkedin_post(_article())
    assert "GPT-5" in post or "LinkedIn" in post or "#AI" in post
    mock_client.models.generate_content.assert_called_once()


@patch("src.generator.GEMINI_API_KEY", "")
def test_raises_without_api_key():
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        generate_linkedin_post(_article())


@patch("src.generator.GEMINI_RETRY_WAIT_MIN", 0)
@patch("src.generator.GEMINI_RETRY_WAIT_MAX", 0)
@patch("src.generator.GEMINI_API_KEY", "fake-key")
@patch("src.generator.genai")
def test_retries_on_server_error_then_succeeds(mock_genai):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Retry success post #AI"

    mock_client.models.generate_content.side_effect = [
        _server_error(),
        mock_response,
    ]
    mock_genai.Client.return_value = mock_client

    post = generate_linkedin_post(_article())
    assert "Retry success" in post
    assert mock_client.models.generate_content.call_count == 2


@patch("src.generator.GEMINI_MAX_RETRIES", 2)
@patch("src.generator.GEMINI_RETRY_WAIT_MIN", 0)
@patch("src.generator.GEMINI_RETRY_WAIT_MAX", 0)
@patch("src.generator.GEMINI_API_KEY", "fake-key")
@patch("src.generator.genai")
def test_falls_back_to_secondary_model(mock_genai):
    mock_client = MagicMock()
    fallback_response = MagicMock()
    fallback_response.text = "Fallback model post #AI"

    mock_client.models.generate_content.side_effect = [
        _server_error(),
        _server_error(),
        fallback_response,
    ]
    mock_genai.Client.return_value = mock_client

    post = generate_linkedin_post(_article())
    assert "Fallback model" in post
    assert mock_client.models.generate_content.call_count == 3


@patch("src.generator.GEMINI_MAX_RETRIES", 2)
@patch("src.generator.GEMINI_RETRY_WAIT_MIN", 0)
@patch("src.generator.GEMINI_RETRY_WAIT_MAX", 0)
@patch("src.generator.GEMINI_API_KEY", "fake-key")
@patch("src.generator.genai")
def test_raises_when_both_models_fail(mock_genai):
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = _server_error()
    mock_genai.Client.return_value = mock_client

    with pytest.raises(ServerError):
        generate_linkedin_post(_article())
