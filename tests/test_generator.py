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


# Valid post that passes all validation checks
_VALID_POST = (
    "OpenAI has launched GPT-5, a major leap in AI reasoning capabilities. "
    "This new model shows significant improvements in coding and mathematics. "
    "The transformer architecture enables breakthrough performance on complex tasks. "
    "https://example.com/gpt5\n\n"
    "#AI #OpenAI #GPT5 #MachineLearning"
)


def _mock_client_with_response(response_text: str):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = response_text
    mock_client.models.generate_content.return_value = mock_response
    return mock_client


@patch("src.generator.GEMINI_API_KEY", "fake-key")
@patch("src.generator.genai")
def test_generate_returns_post(mock_genai):
    mock_genai.Client.return_value = _mock_client_with_response(_VALID_POST)

    post = generate_linkedin_post(_article())
    assert "GPT-5" in post or "AI" in post
    assert "https://example.com/gpt5" in post
    assert post.count("#") >= 3
    mock_genai.Client.return_value.models.generate_content.assert_called_once()


@patch("src.generator.GEMINI_API_KEY", "")
def test_raises_without_api_key():
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        generate_linkedin_post(_article())


@patch("src.generator.GEMINI_MAX_RETRIES", 2)
@patch("src.generator.GEMINI_RETRY_WAIT_MIN", 0)
@patch("src.generator.GEMINI_RETRY_WAIT_MAX", 0)
@patch("src.generator.GEMINI_API_KEY", "fake-key")
@patch("src.generator.genai")
def test_retries_on_server_error_then_succeeds(mock_genai):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = _VALID_POST
    mock_client.models.generate_content.side_effect = [
        _server_error(),
        mock_response,
    ]
    mock_genai.Client.return_value = mock_client

    post = generate_linkedin_post(_article())
    assert "GPT-5" in post
    assert mock_client.models.generate_content.call_count == 2


@patch("src.generator.GEMINI_MAX_RETRIES", 2)
@patch("src.generator.GEMINI_RETRY_WAIT_MIN", 0)
@patch("src.generator.GEMINI_RETRY_WAIT_MAX", 0)
@patch("src.generator.GEMINI_API_KEY", "fake-key")
@patch("src.generator.GEMINI_MAX_CALLS_PER_ARTICLE", 4)
@patch("src.generator.genai")
def test_falls_back_to_secondary_model(mock_genai):
    mock_client = MagicMock()

    # Primary model fails twice (retries), then fallback succeeds
    fallback_response = MagicMock()
    fallback_response.text = _VALID_POST

    mock_client.models.generate_content.side_effect = [
        _server_error(),  # primary attempt 1
        _server_error(),  # primary attempt 2 (retry)
        _server_error(),  # primary attempt 3 (retry) - exhausted
        fallback_response,  # fallback attempt 1
    ]
    mock_genai.Client.return_value = mock_client

    post = generate_linkedin_post(_article())
    assert "GPT-5" in post
    # 3 primary + 1 fallback = 4 calls
    assert mock_client.models.generate_content.call_count == 4


@patch("src.generator.GEMINI_MAX_RETRIES", 2)
@patch("src.generator.GEMINI_RETRY_WAIT_MIN", 0)
@patch("src.generator.GEMINI_RETRY_WAIT_MAX", 0)
@patch("src.generator.GEMINI_API_KEY", "fake-key")
@patch("src.generator.genai")
def test_raises_when_both_models_fail(mock_genai):
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = _server_error()
    mock_genai.Client.return_value = mock_client

    with pytest.raises(ValueError, match="Per-article LLM call budget exhausted"):
        generate_linkedin_post(_article())
    assert mock_client.models.generate_content.call_count == 2
