"""Tests for training data → memory_items sync pipeline.

Covers:
  - Strava activity content formatting (all fields, minimal, null fields)
  - Strava activity sync: creates RawMemory + MemoryItem, supersession on update
  - Commitment summary content formatting (daily and aggregate)
  - Commitment summary sync: creates RawMemory + MemoryItem, supersession
  - Constants: AUTO_CAPTURE_SOURCES and TASK_SKIP_SOURCES contain new sources
  - detect_misses() triggers commitment summary on aggregate completion
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from src.core.models import (
    Commitment,
    CommitmentEntry,
    MemoryItem,
    RawMemory,
    StravaActivity,
)


# ── Strava activity content formatting ────────────────────────────────────────


def test_format_strava_activity_content_all_fields():
    """Activity with all fields produces a complete natural-language string."""
    from src.pipeline.training_sync import _format_strava_activity_content

    activity = StravaActivity(
        strava_id=12345,
        activity_type="Ride",
        name="Morning Ride",
        distance_m=45000.0,
        duration_s=5400,
        tss=120.5,
        avg_power_w=210.0,
        avg_hr=145,
        elevation_m=350.0,
        started_at=datetime(2026, 4, 10, 8, 0, tzinfo=UTC),
    )

    content = _format_strava_activity_content(activity)

    assert "Ride" in content
    assert "Morning Ride" in content
    assert "2026-04-10" in content
    assert "45.0 km" in content
    assert "120.5" in content  # TSS
    assert "210" in content  # avg power
    assert "145" in content  # avg HR
    assert "350" in content  # elevation


def test_format_strava_activity_content_minimal():
    """Activity with only required fields omits null metric clauses."""
    from src.pipeline.training_sync import _format_strava_activity_content

    activity = StravaActivity(
        strava_id=12345,
        activity_type="Run",
        name="Easy jog",
        started_at=datetime(2026, 4, 10, 8, 0, tzinfo=UTC),
    )

    content = _format_strava_activity_content(activity)

    assert "Run" in content
    assert "Easy jog" in content
    assert "2026-04-10" in content
    assert "km" not in content
    assert "TSS" not in content
    assert "power" not in content
    assert "HR" not in content


def test_format_strava_activity_content_null_fields():
    """Activity with some null fields handles gracefully."""
    from src.pipeline.training_sync import _format_strava_activity_content

    activity = StravaActivity(
        strava_id=12345,
        activity_type="Ride",
        name="Commute",
        distance_m=10000.0,
        duration_s=1800,
        tss=None,
        avg_power_w=None,
        avg_hr=None,
        elevation_m=None,
        started_at=datetime(2026, 4, 10, 8, 0, tzinfo=UTC),
    )

    content = _format_strava_activity_content(activity)

    assert "10.0 km" in content
    assert "TSS" not in content
    assert "power" not in content


# ── Strava activity DB sync ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_strava_activity_creates_raw_and_memory(async_session):
    """sync_strava_activity_to_memory() creates RawMemory + MemoryItem."""
    from src.pipeline.training_sync import sync_strava_activity_to_memory

    activity = StravaActivity(
        strava_id=99999,
        activity_type="Ride",
        name="Test Ride",
        distance_m=30000.0,
        duration_s=3600,
        tss=80.0,
        started_at=datetime(2026, 4, 10, 8, 0, tzinfo=UTC),
    )
    async_session.add(activity)
    await async_session.commit()
    await async_session.refresh(activity)

    with patch(
        "src.pipeline.training_sync.embed_text",
        new_callable=AsyncMock,
        return_value=[0.1] * 1024,
    ):
        result = await sync_strava_activity_to_memory(
            async_session, activity, AsyncMock()
        )

    assert result is not None

    # Verify RawMemory
    raw_result = await async_session.execute(
        select(RawMemory).where(RawMemory.source == "strava-activity")
    )
    raw = raw_result.scalar_one()
    assert raw.metadata_["strava_activity_id"] == "99999"

    # Verify MemoryItem
    mi_result = await async_session.execute(
        select(MemoryItem).where(MemoryItem.raw_id == raw.id)
    )
    mi = mi_result.scalar_one()
    assert mi.type == "strava_activity"
    assert "Test Ride" in mi.content
    assert float(mi.base_importance) == 0.4
    assert "training:strava" in mi.tags
    assert "strava:ride" in mi.tags


@pytest.mark.asyncio
async def test_sync_strava_activity_supersedes_on_update(async_session):
    """Re-syncing same strava_id supersedes old MemoryItem."""
    from src.pipeline.training_sync import sync_strava_activity_to_memory

    activity = StravaActivity(
        strava_id=88888,
        activity_type="Ride",
        name="Original Name",
        distance_m=20000.0,
        duration_s=3600,
        started_at=datetime(2026, 4, 10, 8, 0, tzinfo=UTC),
    )
    async_session.add(activity)
    await async_session.commit()
    await async_session.refresh(activity)

    with patch(
        "src.pipeline.training_sync.embed_text",
        new_callable=AsyncMock,
        return_value=[0.1] * 1024,
    ):
        await sync_strava_activity_to_memory(async_session, activity, AsyncMock())

    # Update name and re-sync
    activity.name = "Updated Name"
    await async_session.commit()

    with patch(
        "src.pipeline.training_sync.embed_text",
        new_callable=AsyncMock,
        return_value=[0.2] * 1024,
    ):
        await sync_strava_activity_to_memory(async_session, activity, AsyncMock())

    # Old should be superseded, new should not
    mi_result = await async_session.execute(
        select(MemoryItem).order_by(MemoryItem.created_at)
    )
    items = list(mi_result.scalars().all())
    assert len(items) == 2
    assert items[0].is_superseded is True
    assert items[1].is_superseded is False
    assert "Updated Name" in items[1].content


# ── Commitment summary content formatting ────────────────────────────────────


def test_format_commitment_summary_daily():
    """Daily commitment completion produces correct narrative."""
    from src.pipeline.training_sync import _format_commitment_summary_content

    commitment = Commitment(
        name="Push-ups challenge",
        exercise="push-ups",
        daily_target=50,
        metric="reps",
        cadence="daily",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 10),
        status="completed",
    )
    entries = [
        CommitmentEntry(entry_date=date(2026, 4, 1), status="hit", logged_count=55),
        CommitmentEntry(entry_date=date(2026, 4, 2), status="hit", logged_count=50),
        CommitmentEntry(entry_date=date(2026, 4, 3), status="miss", logged_count=0),
        CommitmentEntry(entry_date=date(2026, 4, 4), status="hit", logged_count=60),
        CommitmentEntry(entry_date=date(2026, 4, 5), status="hit", logged_count=50),
        CommitmentEntry(entry_date=date(2026, 4, 6), status="hit", logged_count=50),
        CommitmentEntry(entry_date=date(2026, 4, 7), status="hit", logged_count=50),
        CommitmentEntry(entry_date=date(2026, 4, 8), status="hit", logged_count=50),
        CommitmentEntry(entry_date=date(2026, 4, 9), status="hit", logged_count=50),
        CommitmentEntry(entry_date=date(2026, 4, 10), status="hit", logged_count=50),
    ]

    content = _format_commitment_summary_content(commitment, entries)

    assert "Push-ups challenge" in content
    assert "push-ups" in content
    assert "2026-04-01" in content
    assert "2026-04-10" in content
    assert "9/10" in content  # 9 hits out of 10
    assert "90" in content  # 90% completion rate
    assert "streak" in content.lower()


def test_format_commitment_summary_aggregate():
    """Aggregate commitment produces narrative with targets and progress."""
    from src.pipeline.training_sync import _format_commitment_summary_content

    commitment = Commitment(
        name="April cycling",
        exercise="cycling",
        daily_target=0,
        metric="km",
        cadence="aggregate",
        targets={"km": 200, "tss": 400},
        progress={"km": 185.5, "tss": 380.0},
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 30),
        status="completed",
    )

    content = _format_commitment_summary_content(commitment, [])

    assert "April cycling" in content
    assert "aggregate" in content
    assert "200" in content  # target km
    assert "185.5" in content  # progress km


# ── Commitment summary DB sync ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_commitment_summary_creates_raw_and_memory(async_session):
    """sync_commitment_summary_to_memory() creates RawMemory + MemoryItem."""
    from src.pipeline.training_sync import sync_commitment_summary_to_memory

    commitment = Commitment(
        name="Test Challenge",
        exercise="push-ups",
        daily_target=50,
        metric="reps",
        cadence="daily",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 7),
        status="completed",
    )
    async_session.add(commitment)
    await async_session.commit()
    await async_session.refresh(commitment)

    # Add some entries
    for i in range(7):
        entry = CommitmentEntry(
            commitment_id=commitment.id,
            entry_date=date(2026, 4, 1) + timedelta(days=i),
            status="hit" if i < 5 else "miss",
            logged_count=50 if i < 5 else 0,
        )
        async_session.add(entry)
    await async_session.commit()

    with patch(
        "src.pipeline.training_sync.embed_text",
        new_callable=AsyncMock,
        return_value=[0.1] * 1024,
    ):
        result = await sync_commitment_summary_to_memory(
            async_session, commitment, AsyncMock()
        )

    assert result is not None

    # Verify RawMemory
    raw_result = await async_session.execute(
        select(RawMemory).where(RawMemory.source == "commitment-summary")
    )
    raw = raw_result.scalar_one()
    assert raw.metadata_["commitment_id"] == str(commitment.id)

    # Verify MemoryItem
    mi_result = await async_session.execute(
        select(MemoryItem).where(MemoryItem.raw_id == raw.id)
    )
    mi = mi_result.scalar_one()
    assert mi.type == "commitment_summary"
    assert "Test Challenge" in mi.content
    assert float(mi.base_importance) == 0.7
    assert "training:commitment" in mi.tags
    assert "commitment:completed" in mi.tags


@pytest.mark.asyncio
async def test_sync_commitment_summary_supersedes_on_re_run(async_session):
    """Re-running for same commitment_id supersedes old MemoryItem."""
    from src.pipeline.training_sync import sync_commitment_summary_to_memory

    commitment = Commitment(
        name="Test Challenge",
        exercise="push-ups",
        daily_target=50,
        metric="reps",
        cadence="daily",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 3),
        status="completed",
    )
    async_session.add(commitment)
    await async_session.commit()
    await async_session.refresh(commitment)

    with patch(
        "src.pipeline.training_sync.embed_text",
        new_callable=AsyncMock,
        return_value=[0.1] * 1024,
    ):
        await sync_commitment_summary_to_memory(async_session, commitment, AsyncMock())
        await sync_commitment_summary_to_memory(async_session, commitment, AsyncMock())

    mi_result = await async_session.execute(
        select(MemoryItem).order_by(MemoryItem.created_at)
    )
    items = list(mi_result.scalars().all())
    assert len(items) == 2
    assert items[0].is_superseded is True
    assert items[1].is_superseded is False


# ── Constants ────────────────────────────────────────────────────────────────


def test_auto_capture_sources_contains_strava():
    """strava-activity must be in AUTO_CAPTURE_SOURCES."""
    from src.pipeline.constants import AUTO_CAPTURE_SOURCES

    assert "strava-activity" in AUTO_CAPTURE_SOURCES


def test_task_skip_sources_contains_commitment_summary():
    """commitment-summary must be in TASK_SKIP_SOURCES."""
    from src.pipeline.constants import TASK_SKIP_SOURCES

    assert "commitment-summary" in TASK_SKIP_SOURCES


def test_task_skip_sources_contains_strava():
    """strava-activity must be in TASK_SKIP_SOURCES (already exists)."""
    from src.pipeline.constants import TASK_SKIP_SOURCES

    assert "strava-activity" in TASK_SKIP_SOURCES


# ── detect_misses commitment summary hook ────────────────────────────────────


@pytest.mark.asyncio
async def test_detect_misses_triggers_commitment_summary(async_session):
    """detect_misses() calls sync_commitment_summary_to_memory for completed aggregates."""
    from unittest.mock import MagicMock

    from src.jobs.commitment_miss import detect_misses

    # Create an aggregate commitment ending yesterday
    yesterday = date(2026, 4, 10)
    commitment = Commitment(
        name="April cycling",
        exercise="cycling",
        daily_target=0,
        metric="km",
        cadence="aggregate",
        targets={"km": 200},
        progress={"km": 150},
        start_date=date(2026, 4, 1),
        end_date=yesterday,
        status="active",
    )
    async_session.add(commitment)
    await async_session.commit()

    mock_sync = AsyncMock()

    # Patch get_db_context to use our test session
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_db_context():
        yield async_session

    with patch("src.jobs.commitment_miss._get_yesterday", return_value=yesterday):
        with patch("src.jobs.commitment_miss.get_db_context", mock_db_context):
            with patch(
                "src.pipeline.training_sync.sync_commitment_summary_to_memory",
                mock_sync,
            ):
                with patch("src.llm.client.embedding_client", MagicMock()):
                    await detect_misses()

    # Verify the commitment was marked as completed
    await async_session.refresh(commitment)
    assert commitment.status == "completed"

    # Verify sync was called with the commitment
    assert mock_sync.called
    call_args = mock_sync.call_args
    assert call_args[0][1].id == commitment.id
