"""Tests for the pulse → memory_items sync pipeline.

Covers:
  - Content formatting for all fields, minimal fields, and no data
  - Full DB sync: creates RawMemory + MemoryItem
  - Supersession on re-sync
  - Graceful failure when embedding fails
  - Skip when no embedding client
  - Route-level _try_pulse_sync wrapper
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from src.core.models import DailyPulse, MemoryItem, RawMemory
from src.pipeline.pulse_sync import _format_pulse_content, sync_pulse_to_memory

# ── Unit tests: content formatting ──────────────────────────────────────────


def test_format_pulse_content_all_fields():
    """Pulse with all fields produces a complete natural-language string."""
    pulse = DailyPulse(
        pulse_date=datetime(2026, 4, 8, tzinfo=UTC),
        sleep_quality=4,
        energy_level=3,
        wake_time="07:30",
        notes="felt groggy after late dinner",
        ai_question="What's blocking your top priority?",
        ai_question_response="Need to focus on the API redesign",
        status="completed",
    )

    content = _format_pulse_content(pulse)

    assert "Daily pulse for 2026-04-08:" in content
    assert "Sleep quality 4/5" in content
    assert "energy level 3/5" in content
    assert "woke at 07:30" in content
    assert "Notes: felt groggy after late dinner" in content
    assert "AI question: What's blocking your top priority?" in content
    assert "Response: Need to focus on the API redesign" in content


def test_format_pulse_content_minimal():
    """Pulse with only sleep_quality omits missing-field clauses."""
    pulse = DailyPulse(
        pulse_date=datetime(2026, 4, 8, tzinfo=UTC),
        sleep_quality=3,
        status="completed",
    )

    content = _format_pulse_content(pulse)

    assert "Daily pulse for 2026-04-08:" in content
    assert "Sleep quality 3/5" in content
    assert "energy level" not in content
    assert "woke at" not in content
    assert "Notes:" not in content
    assert "AI question:" not in content


def test_format_pulse_content_no_data():
    """Pulse with no data fields produces a date-only string."""
    pulse = DailyPulse(
        pulse_date=datetime(2026, 4, 8, tzinfo=UTC),
        status="completed",
    )

    content = _format_pulse_content(pulse)

    assert content == "Daily pulse for 2026-04-08:"


def test_format_pulse_content_ai_question_without_response():
    """AI question without response is omitted (both must be present)."""
    pulse = DailyPulse(
        pulse_date=datetime(2026, 4, 8, tzinfo=UTC),
        sleep_quality=4,
        ai_question="What's one thing you want to accomplish today?",
        status="completed",
    )

    content = _format_pulse_content(pulse)

    assert "AI question:" not in content
    assert "Sleep quality 4/5" in content


def test_format_pulse_content_open_signal_renders_as_question():
    """signal_type='open' keeps the legacy 'AI question:' framing."""
    pulse = DailyPulse(
        pulse_date=datetime(2026, 4, 8, tzinfo=UTC),
        sleep_quality=4,
        ai_question="What will make today feel like a win?",
        ai_question_response="Finishing the migration PR",
        signal_type="open",
        status="completed",
    )

    content = _format_pulse_content(pulse)

    assert "Daily pulse for 2026-04-08:" in content
    assert "AI question:" in content
    assert "Response: Finishing the migration PR" in content


def test_format_pulse_content_focus_signal_renders_as_remark():
    """Non-'open' signal types use a signal-tagged framing, not 'AI question:'."""
    pulse = DailyPulse(
        pulse_date=datetime(2026, 4, 8, tzinfo=UTC),
        sleep_quality=4,
        ai_question="Tough 1:1 on the calendar — what outcome do you want?",
        ai_question_response="Clarify scope",
        signal_type="focus",
        status="completed",
    )

    content = _format_pulse_content(pulse)

    assert "Daily pulse (focus) for 2026-04-08:" in content
    assert "AI question:" not in content
    assert "Clarify scope" in content


def test_format_pulse_content_opportunity_signal_renders_as_remark():
    pulse = DailyPulse(
        pulse_date=datetime(2026, 4, 8, tzinfo=UTC),
        ai_question="Best ride weather this week — take advantage.",
        ai_question_response="Will do",
        signal_type="opportunity",
        status="completed",
    )

    content = _format_pulse_content(pulse)

    assert "Daily pulse (opportunity) for 2026-04-08:" in content
    assert "AI question:" not in content


def test_format_pulse_content_legacy_null_signal_type():
    """Rows predating the migration (signal_type=None) keep the old framing."""
    pulse = DailyPulse(
        pulse_date=datetime(2026, 4, 8, tzinfo=UTC),
        ai_question="Legacy Q?",
        ai_question_response="Legacy A",
        signal_type=None,
        status="completed",
    )

    content = _format_pulse_content(pulse)

    assert "Daily pulse for 2026-04-08:" in content
    assert "AI question: Legacy Q?" in content


# ── DB integration tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_creates_raw_memory_and_memory_item(async_session):
    """sync_pulse_to_memory() creates RawMemory(source='daily-pulse') and MemoryItem(type='daily_pulse')."""
    pulse = DailyPulse(
        pulse_date=datetime(2026, 4, 8, tzinfo=UTC),
        sleep_quality=4,
        energy_level=3,
        wake_time="07:30",
        notes="feeling good",
        status="completed",
    )
    async_session.add(pulse)
    await async_session.commit()
    await async_session.refresh(pulse)

    with patch("src.pipeline.pulse_sync.embed_text", new_callable=AsyncMock, return_value=[0.1] * 1024):
        await sync_pulse_to_memory(async_session, pulse, AsyncMock())

    # Verify RawMemory created
    raw_result = await async_session.execute(
        select(RawMemory).where(RawMemory.source == "daily-pulse")
    )
    raw = raw_result.scalar_one()
    assert raw.metadata_["pulse_id"] == str(pulse.id)

    # Verify MemoryItem created
    mi_result = await async_session.execute(
        select(MemoryItem).where(MemoryItem.raw_id == raw.id)
    )
    mi = mi_result.scalar_one()
    assert mi.type == "daily_pulse"
    assert "Sleep quality 4/5" in mi.content
    assert "energy level 3/5" in mi.content
    assert float(mi.base_importance) == 0.5


@pytest.mark.asyncio
async def test_sync_supersedes_on_re_sync(async_session):
    """Re-syncing a pulse supersedes the old memory_item."""
    pulse = DailyPulse(
        pulse_date=datetime(2026, 4, 8, tzinfo=UTC),
        sleep_quality=3,
        status="completed",
    )
    async_session.add(pulse)
    await async_session.commit()
    await async_session.refresh(pulse)

    with patch("src.pipeline.pulse_sync.embed_text", new_callable=AsyncMock, return_value=[0.1] * 1024):
        await sync_pulse_to_memory(async_session, pulse, AsyncMock())

    # Update pulse and re-sync
    pulse.sleep_quality = 4
    pulse.notes = "actually slept better than I thought"
    await async_session.commit()

    with patch("src.pipeline.pulse_sync.embed_text", new_callable=AsyncMock, return_value=[0.2] * 1024):
        await sync_pulse_to_memory(async_session, pulse, AsyncMock())

    # Old should be superseded, new should not
    mi_result = await async_session.execute(
        select(MemoryItem).order_by(MemoryItem.created_at)
    )
    items = mi_result.scalars().all()
    assert len(items) == 2
    assert items[0].is_superseded is True
    assert items[1].is_superseded is False
    assert "Sleep quality 4/5" in items[1].content
    assert "actually slept better" in items[1].content


@pytest.mark.asyncio
async def test_sync_raises_on_embedding_failure(async_session):
    """sync_pulse_to_memory() raises on embedding failure (caller catches)."""
    pulse = DailyPulse(
        pulse_date=datetime(2026, 4, 8, tzinfo=UTC),
        sleep_quality=3,
        status="completed",
    )
    async_session.add(pulse)
    await async_session.commit()
    await async_session.refresh(pulse)

    with patch("src.pipeline.pulse_sync.embed_text", new_callable=AsyncMock, side_effect=RuntimeError("embed failed")):
        with pytest.raises(RuntimeError, match="embed failed"):
            await sync_pulse_to_memory(async_session, pulse, AsyncMock())


@pytest.mark.asyncio
async def test_try_pulse_sync_catches_exceptions(async_session):
    """_try_pulse_sync catches all exceptions and logs them."""
    from src.api.routes.pulse import _try_pulse_sync

    pulse = DailyPulse(
        pulse_date=datetime(2026, 4, 8, tzinfo=UTC),
        sleep_quality=3,
        status="completed",
    )
    async_session.add(pulse)
    await async_session.commit()
    await async_session.refresh(pulse)

    with patch("src.llm.client.embedding_client", AsyncMock()):
        with patch(
            "src.pipeline.pulse_sync.sync_pulse_to_memory",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            # Should NOT raise
            await _try_pulse_sync(async_session, pulse)


@pytest.mark.asyncio
async def test_try_pulse_sync_skips_without_embedding_client(async_session):
    """_try_pulse_sync logs warning and returns without error when embedding_client is None."""
    from structlog.testing import capture_logs

    from src.api.routes.pulse import _try_pulse_sync

    pulse = DailyPulse(
        pulse_date=datetime(2026, 4, 8, tzinfo=UTC),
        sleep_quality=3,
        status="completed",
    )
    async_session.add(pulse)
    await async_session.commit()
    await async_session.refresh(pulse)

    with patch("src.llm.client.embedding_client", None):
        with capture_logs() as cap:
            await _try_pulse_sync(async_session, pulse)

    skip_events = [e for e in cap if e.get("event") == "pulse_sync_skipped_no_embedding_client"]
    assert len(skip_events) == 1
