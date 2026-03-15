"""Targeted tests for base_importance behavior in the extraction pipeline.

Verifies that:
- Claude-assigned importance scores pass through correctly (no hardcoding)
- Pydantic schema validation enforces 0.0–1.0 range
- Correct prompt is selected per attempt number
- Default fallback works when base_importance is absent from LLM response
"""

import json
from unittest.mock import AsyncMock

import pytest

from src.llm.client import AnthropicClient, ExtractionFailed
from src.llm.prompts import (
    EXTRACTION_RETRY_PROMPT_1,
    EXTRACTION_RETRY_PROMPT_2,
    EXTRACTION_SYSTEM_PROMPT,
)
from src.pipeline.extractor import extract

# ── Helpers ───────────────────────────────────────────────────────────────────


def _valid_json(base_importance: float = 0.6, **overrides: object) -> str:
    payload = {
        "type": "memory",
        "content": "test content",
        "summary": "test summary",
        "entities": [],
        "decisions": [],
        "tasks": [],
        "base_importance": base_importance,
        **overrides,
    }
    return json.dumps(payload)


def _mock_client(response: str) -> AsyncMock:
    client = AsyncMock(spec=AnthropicClient)
    client.complete.return_value = response
    return client


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_base_importance_high_value_passes_through() -> None:
    """High importance score assigned by Claude is preserved unchanged."""
    result = await extract("We made an irreversible architecture decision.", attempt=0, client=_mock_client(_valid_json(0.9)))
    assert result.base_importance >= 0.8


@pytest.mark.asyncio
async def test_extract_base_importance_low_value_passes_through() -> None:
    """Low importance score assigned by Claude is preserved unchanged."""
    result = await extract("Lunch order is pizza today.", attempt=0, client=_mock_client(_valid_json(0.2)))
    assert result.base_importance <= 0.4


@pytest.mark.asyncio
async def test_extract_base_importance_is_float_in_valid_range() -> None:
    """A mid-range score is stored as a float within [0.0, 1.0]."""
    result = await extract("Some context note.", attempt=0, client=_mock_client(_valid_json(0.75)))
    assert isinstance(result.base_importance, float)
    assert 0.0 <= result.base_importance <= 1.0


@pytest.mark.asyncio
async def test_extract_base_importance_rejects_above_1_0() -> None:
    """Score above 1.0 raises ExtractionFailed (Pydantic ge/le validation)."""
    with pytest.raises(ExtractionFailed):
        await extract("text", attempt=0, client=_mock_client(_valid_json(1.5)))


@pytest.mark.asyncio
async def test_extract_base_importance_rejects_below_0_0() -> None:
    """Negative score raises ExtractionFailed."""
    with pytest.raises(ExtractionFailed):
        await extract("text", attempt=0, client=_mock_client(_valid_json(-0.1)))


@pytest.mark.asyncio
async def test_extract_base_importance_defaults_when_missing() -> None:
    """When base_importance is absent, Pydantic default of 0.5 is applied."""
    payload = json.dumps({"type": "memory", "content": "test", "entities": [], "decisions": [], "tasks": []})
    result = await extract("text", attempt=0, client=_mock_client(payload))
    assert result.base_importance == 0.5


@pytest.mark.asyncio
async def test_extract_base_importance_valid_at_boundaries() -> None:
    """Boundary values 0.0 and 1.0 are both accepted by the schema."""
    result_low = await extract("text", attempt=0, client=_mock_client(_valid_json(0.0)))
    assert result_low.base_importance == 0.0

    result_high = await extract("text", attempt=0, client=_mock_client(_valid_json(1.0)))
    assert result_high.base_importance == 1.0


@pytest.mark.asyncio
async def test_extract_uses_correct_prompt_per_attempt() -> None:
    """Each attempt number routes to the correct system prompt."""
    client = _mock_client(_valid_json())

    await extract("text", attempt=0, client=client)
    assert client.complete.call_args_list[-1].kwargs["system_prompt"] == EXTRACTION_SYSTEM_PROMPT

    await extract("text", attempt=1, client=client)
    assert client.complete.call_args_list[-1].kwargs["system_prompt"] == EXTRACTION_RETRY_PROMPT_1

    await extract("text", attempt=2, client=client)
    assert client.complete.call_args_list[-1].kwargs["system_prompt"] == EXTRACTION_RETRY_PROMPT_2
