"""Unit tests for AI service with mocked Groq responses."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai_service import AIResult, _clean_json, analyze_vacancy


def test_clean_json_strips_markdown():
    raw = "```json\n{\"technologies\": []}\n```"
    assert _clean_json(raw) == '{"technologies": []}'


def test_clean_json_plain():
    raw = '{"technologies": ["Python"]}'
    assert _clean_json(raw) == raw


def _mock_groq_response(json_text: str):
    """Build a mock that mimics Groq chat completion response."""
    message = MagicMock()
    message.content = json_text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.mark.asyncio
@patch("app.services.ai_service._pick_model", new_callable=AsyncMock, return_value="test-model")
@patch("app.services.ai_service._client")
async def test_analyze_vacancy_dou(mock_client, mock_pick):
    mock_client.chat.completions.create = AsyncMock(
        return_value=_mock_groq_response(
            '{"technologies": ["Python", "Django"], "experience_years": 3, '
            '"english_level": "Upper-Intermediate", '
            '"responsibilities_summary": "Build APIs", '
            '"required_skills_summary": "Python 3+ years"}'
        )
    )

    result = await analyze_vacancy("We need a Python developer with Django...", "DOU")

    assert isinstance(result, AIResult)
    assert "Python" in result.technologies
    assert "Django" in result.technologies
    assert result.experience_years == 3
    assert result.english_level == "B2"  # normalized from Upper-Intermediate
    assert result.responsibilities_summary == "Build APIs"


@pytest.mark.asyncio
@patch("app.services.ai_service._pick_model", new_callable=AsyncMock, return_value="test-model")
@patch("app.services.ai_service._client")
async def test_analyze_vacancy_djinni_reduced_schema(mock_client, mock_pick):
    mock_client.chat.completions.create = AsyncMock(
        return_value=_mock_groq_response(
            '{"technologies": ["FastAPI", "Redis"], '
            '"responsibilities_summary": "Develop microservices", '
            '"required_skills_summary": "FastAPI experience"}'
        )
    )

    result = await analyze_vacancy("Build microservices with FastAPI...", "Djinni")

    assert "FastAPI" in result.technologies
    assert result.responsibilities_summary == "Develop microservices"
    assert result.experience_years is None


@pytest.mark.asyncio
@patch("app.services.ai_service._pick_model", new_callable=AsyncMock, return_value="test-model")
@patch("app.services.ai_service._client")
async def test_analyze_vacancy_returns_none_on_invalid_json(mock_client, mock_pick):
    mock_client.chat.completions.create = AsyncMock(
        return_value=_mock_groq_response("not valid json {{{")
    )

    result = await analyze_vacancy("Some description", "DOU")
    assert result is None


@pytest.mark.asyncio
@patch("app.services.ai_service._pick_model", new_callable=AsyncMock, return_value="test-model")
@patch("app.services.ai_service._client")
async def test_analyze_vacancy_returns_none_on_api_error(mock_client, mock_pick):
    mock_client.chat.completions.create = AsyncMock(
        side_effect=Exception("API quota exceeded")
    )

    result = await analyze_vacancy("Some description", "DOU")
    assert result is None


@pytest.mark.asyncio
async def test_analyze_vacancy_skips_empty_description():
    result = await analyze_vacancy("", "DOU")
    assert result is None
