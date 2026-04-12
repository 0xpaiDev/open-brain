"""Tests for the daily importance aggregation job (src/jobs/importance.py).

Covers:
  - run_importance_job(): full job integration on in-memory SQLite
  - _compute_weighted_score(): pure math helper

Test naming: test_<function>_<scenario> per CLAUDE.md conventions.
External APIs (Anthropic, Voyage) are never touched — all tests run on SQLite.
"""

import math
from datetime import UTC, datetime, timedelta

import pytest

from src.core.models import MemoryItem, RawMemory, RetrievalEvent
from src.jobs.importance import NORMALIZATION_FACTOR, _compute_weighted_score, run_importance_job

# ── Helpers ────────────────────────────────────────────────────────────────────


async def _make_memory(session, dynamic_importance: float = 0.0) -> MemoryItem:
    """Create a RawMemory + MemoryItem pair and return the MemoryItem."""
    raw = RawMemory(source="test", raw_text="test content")
    session.add(raw)
    await session.flush()

    item = MemoryItem(
        raw_id=raw.id,
        type="memory",
        content="test content",
        embedding=[0.0] * 1024,
        dynamic_importance=dynamic_importance,
    )
    session.add(item)
    await session.flush()
    return item


async def _make_event(session, memory_id, age_days: float = 0.0) -> RetrievalEvent:
    """Create a RetrievalEvent with a specific age (simulated via retrieved_at)."""
    retrieved_at = datetime.now(UTC) - timedelta(days=age_days)
    event = RetrievalEvent(memory_id=memory_id, retrieved_at=retrieved_at)
    session.add(event)
    await session.flush()
    return event


# ── run_importance_job tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_importance_job_no_data(async_session):
    """Empty DB: job completes without error and returns zero counts."""
    result = await run_importance_job(async_session)

    assert result["updated"] == 0
    assert result["decayed"] == 0


@pytest.mark.asyncio
async def test_run_importance_job_updates_dynamic_importance(async_session):
    """Memory with a recent retrieval event gets dynamic_importance > 0."""
    item = await _make_memory(async_session)
    await _make_event(async_session, item.id, age_days=0.0)
    await async_session.commit()

    result = await run_importance_job(async_session)

    assert result["updated"] == 1
    assert result["decayed"] == 0

    updated = await async_session.get(MemoryItem, item.id)
    assert float(updated.dynamic_importance) > 0.0


@pytest.mark.asyncio
async def test_run_importance_job_older_events_have_less_weight(async_session):
    """Memory with recent events outscores memory with old events."""
    item_recent = await _make_memory(async_session)
    item_old = await _make_memory(async_session)

    await _make_event(async_session, item_recent.id, age_days=1.0)
    await _make_event(async_session, item_old.id, age_days=60.0)
    await async_session.commit()

    await run_importance_job(async_session)

    recent = await async_session.get(MemoryItem, item_recent.id)
    old = await async_session.get(MemoryItem, item_old.id)

    assert float(recent.dynamic_importance) > float(old.dynamic_importance)


@pytest.mark.asyncio
async def test_run_importance_job_caps_at_1_0(async_session):
    """Memory with many recent retrieval events is capped at dynamic_importance=1.0."""
    item = await _make_memory(async_session)
    # Create more events than NORMALIZATION_FACTOR to force saturation
    for _ in range(int(NORMALIZATION_FACTOR) + 5):
        await _make_event(async_session, item.id, age_days=0.0)
    await async_session.commit()

    await run_importance_job(async_session)

    updated = await async_session.get(MemoryItem, item.id)
    assert float(updated.dynamic_importance) <= 1.0


@pytest.mark.asyncio
async def test_run_importance_job_decays_memory_with_no_events(async_session):
    """Memory with dynamic_importance=0.8 but zero retrieval events gets decayed."""
    item = await _make_memory(async_session, dynamic_importance=0.8)
    await async_session.commit()

    result = await run_importance_job(async_session)

    assert result["decayed"] == 1
    assert result["updated"] == 0

    decayed_item = await async_session.get(MemoryItem, item.id)
    assert float(decayed_item.dynamic_importance) < 0.8


@pytest.mark.asyncio
async def test_run_importance_job_leaves_zero_at_zero(async_session):
    """Memory with dynamic_importance=0.0 and no events stays at 0.0."""
    item = await _make_memory(async_session, dynamic_importance=0.0)
    await async_session.commit()

    result = await run_importance_job(async_session)

    assert result["decayed"] == 0

    unchanged = await async_session.get(MemoryItem, item.id)
    assert float(unchanged.dynamic_importance) == 0.0


@pytest.mark.asyncio
async def test_run_importance_job_multiple_memories(async_session):
    """Three memories with different event counts are all processed correctly."""
    item_none = await _make_memory(async_session)
    item_one = await _make_memory(async_session)
    item_many = await _make_memory(async_session)

    await _make_event(async_session, item_one.id, age_days=0.0)
    for _ in range(3):
        await _make_event(async_session, item_many.id, age_days=0.0)
    await async_session.commit()

    result = await run_importance_job(async_session)

    assert result["updated"] == 2  # item_one + item_many

    none_item = await async_session.get(MemoryItem, item_none.id)
    one_item = await async_session.get(MemoryItem, item_one.id)
    many_item = await async_session.get(MemoryItem, item_many.id)

    # item_none has no events and started at 0.0 → stays 0.0
    assert float(none_item.dynamic_importance) == 0.0
    # item_one < item_many (more events = higher score)
    assert float(one_item.dynamic_importance) < float(many_item.dynamic_importance)
    # all scores in valid range
    assert 0.0 <= float(none_item.dynamic_importance) <= 1.0
    assert 0.0 <= float(one_item.dynamic_importance) <= 1.0
    assert 0.0 <= float(many_item.dynamic_importance) <= 1.0


# ── _compute_weighted_score tests ─────────────────────────────────────────────


def test_compute_weighted_score_single_event_today():
    """Event at age=0 days contributes weight=1.0 (exp(0) = 1)."""
    now = datetime.now(UTC)
    event_time = now  # age = 0

    score = _compute_weighted_score([event_time], half_life_days=30, now=now)

    assert score == pytest.approx(1.0, abs=1e-6)


def test_compute_weighted_score_event_at_half_life():
    """Event at age=half_life_days contributes weight=exp(-1) ≈ 0.368."""
    half_life = 30
    now = datetime.now(UTC)
    event_time = now - timedelta(days=half_life)

    score = _compute_weighted_score([event_time], half_life_days=half_life, now=now)

    expected = math.exp(-1.0)  # ≈ 0.368
    assert score == pytest.approx(expected, abs=1e-4)
