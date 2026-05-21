"""Tests for build_briefing() bullet assembly."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from src.pulse_signals.ranker import Signal
from src.pulse_signals.render import build_briefing
from datetime import date


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="Cycling behind — 34 km of 50 km target.")
    return llm


TODAY = date(2026, 5, 21)


class TestBuildBriefing:
    @pytest.mark.asyncio
    async def test_deadline_bullet_single(self, mock_llm):
        signals = [Signal("deadline", 8.0, {"titles": ["Call dentist"], "total_count": 1})]
        result = await build_briefing(signals, llm=mock_llm, today=TODAY)
        assert "• 1 task due today: Call dentist" in result

    @pytest.mark.asyncio
    async def test_deadline_bullet_multiple(self, mock_llm):
        signals = [Signal("deadline", 8.0, {"titles": ["Buy milk", "Call dentist", "Submit report"], "total_count": 5})]
        result = await build_briefing(signals, llm=mock_llm, today=TODAY)
        assert "• 5 tasks due today: Buy milk, Call dentist, Submit report…" in result

    @pytest.mark.asyncio
    async def test_named_day_bullet(self, mock_llm):
        signals = [Signal("named_day", 6.5, {"titles": ["Paulius's birthday"]})]
        result = await build_briefing(signals, llm=mock_llm, today=TODAY)
        assert "• Today: Paulius's birthday" in result

    @pytest.mark.asyncio
    async def test_open_bullet_with_todos_and_events(self, mock_llm):
        signals = [Signal("open", 5.0, {"todo_count": 4, "event_count": 2})]
        result = await build_briefing(signals, llm=mock_llm, today=TODAY)
        assert "• 4 open tasks · 2 event(s) today" in result

    @pytest.mark.asyncio
    async def test_open_bullet_todos_only(self, mock_llm):
        signals = [Signal("open", 5.0, {"todo_count": 3, "event_count": 0})]
        result = await build_briefing(signals, llm=mock_llm, today=TODAY)
        assert "• 3 open tasks — nothing else scheduled" in result

    @pytest.mark.asyncio
    async def test_open_bullet_clear(self, mock_llm):
        signals = [Signal("open", 5.0, {"todo_count": 0, "event_count": 0})]
        result = await build_briefing(signals, llm=mock_llm, today=TODAY)
        assert "• Clear schedule — nothing due or scheduled" in result

    @pytest.mark.asyncio
    async def test_commitment_pace_uses_llm(self, mock_llm):
        signals = [Signal("commitment_pace", 7.5, {
            "name": "Cycling May", "metric": "km",
            "actual": 34.0, "target": 50.0, "pace_overall": 0.68, "is_behind": True
        })]
        result = await build_briefing(signals, llm=mock_llm, today=TODAY)
        mock_llm.complete.assert_called_once()
        assert result.startswith("•")

    @pytest.mark.asyncio
    async def test_multiple_bullets_newline_separated(self, mock_llm):
        signals = [
            Signal("named_day", 6.5, {"titles": ["Women's Day"]}),
            Signal("open", 5.0, {"todo_count": 2, "event_count": 0}),
        ]
        result = await build_briefing(signals, llm=mock_llm, today=TODAY)
        lines = result.split("\n")
        assert len(lines) == 2
        assert all(line.startswith("•") for line in lines)

    @pytest.mark.asyncio
    async def test_empty_signals_returns_fallback(self, mock_llm):
        result = await build_briefing([], llm=mock_llm, today=TODAY)
        assert result == "• Clear schedule — nothing due or scheduled"
