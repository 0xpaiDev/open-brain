"""Rendering tests for pulse signal prompts.

Ensures:
  - Correct prompt routing per signal_type
  - <user_input> delimiters wrap variable content
  - today's ISO date injected into system prompt
  - max_tokens cap enforced (<=80)
  - Haiku failure falls back to the legacy default question
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest

from src.pulse_signals.ranker import Signal
from src.pulse_signals.render import render_signal


def _mock_llm(output: str = "Ship the migration today?") -> AsyncMock:
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=output)
    return llm


@pytest.mark.asyncio
async def test_render_focus_uses_focus_prompt():
    signal = Signal(
        signal_type="focus",
        urgency=7.0,
        payload={"event_title": "1:1 with Boss", "event_start": "14:00", "reason": "keyword:1:1"},
    )
    llm = _mock_llm("What outcome do you want from the 1:1?")
    result = await render_signal(signal, llm=llm, today=date(2026, 4, 23))

    assert result == "What outcome do you want from the 1:1?"
    call = llm.complete.call_args
    system_prompt = call.kwargs["system_prompt"]
    user_content = call.kwargs["user_content"]
    assert "focus" in system_prompt.lower()
    assert "2026-04-23" in system_prompt
    assert "<user_input>" in user_content
    assert "1:1 with Boss" in user_content
    assert call.kwargs["max_tokens"] <= 80


@pytest.mark.asyncio
async def test_render_opportunity_uses_opportunity_prompt():
    signal = Signal(
        signal_type="opportunity",
        urgency=6.0,
        payload={"today_precip_mm": 0.0, "worst_next_3_precip_mm": 4.0, "today_max_temp": 17.0},
    )
    llm = _mock_llm("Dry today, wet the rest of the week — get outside.")
    result = await render_signal(signal, llm=llm, today=date(2026, 4, 23))

    assert "outside" in result
    call = llm.complete.call_args
    system_prompt = call.kwargs["system_prompt"]
    assert "opportunity" in system_prompt.lower() or "remark" in system_prompt.lower()
    assert "2026-04-23" in system_prompt


@pytest.mark.asyncio
async def test_render_open_uses_open_prompt():
    signal = Signal(
        signal_type="open",
        urgency=5.0,
        payload={
            "top_todos": [{"description": "Ship API redesign", "due_date": None}],
            "event_count": 0,
            "yesterday_question": "What drained you?",
        },
    )
    llm = _mock_llm("What would make today feel like a win?")
    result = await render_signal(signal, llm=llm, today=date(2026, 4, 23))

    assert result == "What would make today feel like a win?"
    call = llm.complete.call_args
    user_content = call.kwargs["user_content"]
    assert "<user_input>" in user_content
    assert "Ship API redesign" in user_content


@pytest.mark.asyncio
async def test_render_unknown_signal_type_raises():
    signal = Signal(signal_type="unknown_flavor", urgency=8.0, payload={})
    llm = _mock_llm()
    with pytest.raises(KeyError):
        await render_signal(signal, llm=llm, today=date(2026, 4, 23))


@pytest.mark.asyncio
async def test_render_falls_back_on_llm_failure():
    signal = Signal(
        signal_type="open",
        urgency=5.0,
        payload={"top_todos": [], "event_count": 0, "yesterday_question": None},
    )
    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=RuntimeError("boom"))

    result = await render_signal(signal, llm=llm, today=date(2026, 4, 23))
    assert result == "What's one thing you want to accomplish today?"


@pytest.mark.asyncio
async def test_render_none_llm_falls_back():
    signal = Signal(signal_type="open", urgency=5.0, payload={"top_todos": [], "event_count": 0})
    result = await render_signal(signal, llm=None, today=date(2026, 4, 23))
    assert result == "What's one thing you want to accomplish today?"
