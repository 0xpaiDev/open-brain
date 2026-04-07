"""Tests for the memory refinement queue worker.

CRITICAL TESTS:
- test_claim_batch_reclaims_stale_processing (FIX-2 validation)
- test_3_failure_path_moves_to_dead_letter (FIX-3 validation)

These tests validate the two most critical bug fixes in the worker.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from structlog.testing import capture_logs

from src.core.models import (
    Entity,
    FailedRefinement,
    MemoryItem,
    RawMemory,
    RefinementQueue,
    Task,
)
from src.llm.client import ExtractionFailed
from src.pipeline.extractor import EntityExtract, ExtractionResult, TaskExtract
from src.pipeline.worker import (
    _get_queue_depth,
    claim_batch,
    move_to_dead_letter,
    process_job,
    store_memory_item,
)

# ── claim_batch tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_claim_batch_picks_pending_job(async_session):
    """claim_batch() claims a pending job and marks it as processing."""
    # Insert a raw memory and queue entry
    raw = RawMemory(
        source="api",
        raw_text="test input",
    )
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id)
    async_session.add(queue)
    await async_session.commit()

    # Claim the batch
    claimed = await claim_batch(async_session, batch_size=1)

    assert len(claimed) == 1
    assert claimed[0].id == queue.id
    assert claimed[0].status == "processing"
    assert claimed[0].locked_at is not None
    assert claimed[0].attempts == 1


@pytest.mark.asyncio
async def test_claim_batch_reclaims_stale_processing(async_session):
    """FIX-2: claim_batch() reclaims items locked > TTL seconds ago.

    This is the critical test validating the stale lock reclaim feature.
    """
    # Insert a raw memory
    raw = RawMemory(source="api", raw_text="test")
    async_session.add(raw)
    await async_session.flush()

    # Insert a queue row with status='processing' but locked 6 minutes ago
    # (default TTL is 300 seconds = 5 minutes)
    old_locked_at = datetime.now(UTC) - timedelta(minutes=6)
    queue = RefinementQueue(
        raw_id=raw.id,
        status="processing",
        locked_at=old_locked_at,
        attempts=1,
    )
    async_session.add(queue)
    await async_session.commit()

    # Claim the batch - should reclaim the stale item
    claimed = await claim_batch(async_session, batch_size=1)

    assert len(claimed) == 1
    assert claimed[0].id == queue.id
    assert claimed[0].status == "processing"
    assert claimed[0].locked_at > old_locked_at  # Updated
    assert claimed[0].attempts == 2  # Incremented


@pytest.mark.asyncio
async def test_claim_batch_skips_fresh_processing(async_session):
    """claim_batch() does not reclaim items locked < TTL seconds ago."""
    # Insert a raw memory
    raw = RawMemory(source="api", raw_text="test")
    async_session.add(raw)
    await async_session.flush()

    # Insert a queue row with status='processing' locked 1 minute ago
    recent_locked_at = datetime.now(UTC) - timedelta(minutes=1)
    queue = RefinementQueue(
        raw_id=raw.id,
        status="processing",
        locked_at=recent_locked_at,
        attempts=1,
    )
    async_session.add(queue)
    await async_session.commit()

    # Claim the batch - should NOT reclaim this fresh lock
    claimed = await claim_batch(async_session, batch_size=1)

    assert len(claimed) == 0


# ── process_job tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_job_creates_memory_item(async_session):
    """process_job() successfully processes a job and creates memory_item."""
    # Setup
    raw = RawMemory(source="api", raw_text="test content")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(
        raw_id=raw.id,
        status="processing",
        attempts=1,
    )
    async_session.add(queue)
    await async_session.commit()

    # Mock clients
    mock_anthropic = AsyncMock()
    mock_anthropic.complete.return_value = '{"type": "memory", "content": "test"}'

    mock_voyage = AsyncMock()
    mock_voyage.embed.return_value = [0.1] * 1024

    # Monkeypatch get_db to return our session
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_get_db():
        yield async_session

    with patch("src.pipeline.worker.get_db", return_value=mock_get_db()):
        await process_job(queue, mock_anthropic, mock_voyage)

    # Verify memory_item was created
    result = await async_session.execute(select(MemoryItem).where(MemoryItem.raw_id == raw.id))
    memory_items = result.scalars().all()
    assert len(memory_items) == 1
    assert memory_items[0].content == "test"

    # Verify queue status is 'done'
    queue_check = await async_session.get(RefinementQueue, queue.id)
    assert queue_check.status == "done"


@pytest.mark.asyncio
async def test_process_job_resets_to_pending_on_first_failure(async_session):
    """process_job() resets failed job to pending (attempts < 3)."""
    # Setup
    raw = RawMemory(source="api", raw_text="test content")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(
        raw_id=raw.id,
        status="processing",
        attempts=1,  # First failure
    )
    async_session.add(queue)
    await async_session.commit()

    # Mock anthropic to raise ExtractionFailed
    mock_anthropic = AsyncMock()
    mock_anthropic.complete.side_effect = ExtractionFailed("Test error")

    mock_voyage = AsyncMock()

    # Monkeypatch get_db
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_get_db():
        yield async_session

    with patch("src.pipeline.worker.get_db", return_value=mock_get_db()):
        await process_job(queue, mock_anthropic, mock_voyage)

    # Verify queue status is reset to 'pending'
    queue_check = await async_session.get(RefinementQueue, queue.id)
    assert queue_check.status == "pending"

    # No dead letter row should exist
    dead_letter_result = await async_session.execute(
        select(FailedRefinement).where(FailedRefinement.queue_id == queue.id)
    )
    assert len(dead_letter_result.scalars().all()) == 0


@pytest.mark.asyncio
async def test_3_failure_path_moves_to_dead_letter(async_session):
    """FIX-3: process_job() moves job to dead letter after 3 failed attempts.

    This is the critical test validating the 3-failure dead letter feature.
    When attempts=2 (3rd attempt) and extraction fails, job moves to dead_letter.
    """
    # Setup
    raw = RawMemory(source="api", raw_text="test content")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(
        raw_id=raw.id,
        status="processing",
        attempts=3,  # 3 attempts means 3 failed attempts
    )
    async_session.add(queue)
    await async_session.commit()

    # Mock anthropic to raise ExtractionFailed
    mock_anthropic = AsyncMock()
    mock_anthropic.complete.side_effect = ExtractionFailed("3rd attempt failed")

    mock_voyage = AsyncMock()

    # Monkeypatch get_db
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_get_db():
        yield async_session

    with patch("src.pipeline.worker.get_db", return_value=mock_get_db()):
        await process_job(queue, mock_anthropic, mock_voyage)

    # Verify queue status is 'failed'
    queue_check = await async_session.get(RefinementQueue, queue.id)
    assert queue_check.status == "failed"

    # Verify dead letter row exists
    dead_letter_result = await async_session.execute(
        select(FailedRefinement).where(FailedRefinement.queue_id == queue.id)
    )
    dead_letters = dead_letter_result.scalars().all()
    assert len(dead_letters) == 1
    assert "3rd attempt failed" in dead_letters[0].error_reason


@pytest.mark.asyncio
async def test_process_job_creates_entities_and_links(async_session):
    """process_job() creates entities and memory_entity_links correctly."""
    # Setup
    raw = RawMemory(source="api", raw_text="test")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id, status="processing", attempts=1)
    async_session.add(queue)
    await async_session.commit()

    # Mock clients with entity in response
    mock_anthropic = AsyncMock()
    extraction_json = {
        "type": "memory",
        "content": "test",
        "entities": [{"name": "Alice", "type": "person"}],
    }
    import json

    mock_anthropic.complete.return_value = json.dumps(extraction_json)

    mock_voyage = AsyncMock()
    mock_voyage.embed.return_value = [0.1] * 1024

    # Monkeypatch get_db
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_get_db():
        yield async_session

    with patch("src.pipeline.worker.get_db", return_value=mock_get_db()):
        await process_job(queue, mock_anthropic, mock_voyage)

    # Verify entity was created
    entity_result = await async_session.execute(select(Entity))
    entities = entity_result.scalars().all()
    assert len(entities) >= 1

    # Verify memory_entity_link exists
    from src.core.models import MemoryEntityLink

    link_result = await async_session.execute(select(MemoryEntityLink))
    links = link_result.scalars().all()
    assert len(links) >= 1


# ── Importance capping tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_job_caps_importance_for_claude_code_source(async_session):
    """process_job() caps base_importance at ceiling for source='claude-code'.

    Auto-captured sessions are background work noise. Their importance must not
    exceed auto_capture_importance_ceiling (default 0.4) so intentional memories
    ingested via Discord/CLI always rank higher.
    """
    raw = RawMemory(source="claude-code", raw_text="session transcript")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id, status="processing", attempts=1)
    async_session.add(queue)
    await async_session.commit()

    # Claude assigns a high importance (0.9) — should be capped at 0.4
    mock_anthropic = AsyncMock()
    mock_anthropic.complete.return_value = (
        '{"type": "memory", "content": "session work", "base_importance": 0.9}'
    )
    mock_voyage = AsyncMock()
    mock_voyage.embed.return_value = [0.1] * 1024

    @asynccontextmanager
    async def mock_get_db():
        yield async_session

    with patch("src.pipeline.worker.get_db", return_value=mock_get_db()):
        await process_job(queue, mock_anthropic, mock_voyage)

    result = await async_session.execute(select(MemoryItem).where(MemoryItem.raw_id == raw.id))
    item = result.scalar_one()
    assert item.base_importance <= 0.4


@pytest.mark.asyncio
async def test_process_job_does_not_cap_importance_for_other_sources(async_session):
    """process_job() does NOT cap base_importance for non-claude-code sources.

    Intentional memories from Discord, CLI, or MCP get their full Claude-assigned
    importance score.
    """
    raw = RawMemory(source="discord", raw_text="haircut on 2026-03-25")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id, status="processing", attempts=1)
    async_session.add(queue)
    await async_session.commit()

    mock_anthropic = AsyncMock()
    mock_anthropic.complete.return_value = (
        '{"type": "task", "content": "get haircut", "base_importance": 0.85}'
    )
    mock_voyage = AsyncMock()
    mock_voyage.embed.return_value = [0.1] * 1024

    @asynccontextmanager
    async def mock_get_db():
        yield async_session

    with patch("src.pipeline.worker.get_db", return_value=mock_get_db()):
        await process_job(queue, mock_anthropic, mock_voyage)

    result = await async_session.execute(select(MemoryItem).where(MemoryItem.raw_id == raw.id))
    item = result.scalar_one()
    assert float(item.base_importance) == pytest.approx(0.85)


@pytest.mark.asyncio
async def test_process_job_does_not_cap_when_importance_already_below_ceiling(async_session):
    """process_job() leaves importance unchanged when it's already below ceiling.

    A claude-code session with base_importance=0.3 should stay at 0.3, not be
    raised or altered.
    """
    raw = RawMemory(source="claude-code", raw_text="trivial session")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id, status="processing", attempts=1)
    async_session.add(queue)
    await async_session.commit()

    mock_anthropic = AsyncMock()
    mock_anthropic.complete.return_value = (
        '{"type": "memory", "content": "trivial work", "base_importance": 0.3}'
    )
    mock_voyage = AsyncMock()
    mock_voyage.embed.return_value = [0.1] * 1024

    @asynccontextmanager
    async def mock_get_db():
        yield async_session

    with patch("src.pipeline.worker.get_db", return_value=mock_get_db()):
        await process_job(queue, mock_anthropic, mock_voyage)

    result = await async_session.execute(select(MemoryItem).where(MemoryItem.raw_id == raw.id))
    item = result.scalar_one()
    assert float(item.base_importance) == pytest.approx(0.3)


# ── store_memory_item tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_memory_item_creates_memory_item(async_session):
    """store_memory_item() creates memory_item, entity_links, decisions, tasks."""
    # Setup (no transaction yet)
    raw = RawMemory(source="api", raw_text="test")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id)
    async_session.add(queue)
    await async_session.flush()

    extraction = ExtractionResult(
        type="memory",
        content="test",
        entities=[EntityExtract(name="Alice", type="person")],
    )
    embedding = [0.1] * 1024

    # Call store_memory_item (it starts its own transaction)
    memory_item = await store_memory_item(async_session, raw, queue, extraction, embedding, [])

    # Verify memory_item exists
    assert memory_item is not None
    assert memory_item.content == "test"

    # Verify queue status was set to 'done'
    queue_check = await async_session.get(RefinementQueue, queue.id)
    assert queue_check.status == "done"


@pytest.mark.asyncio
async def test_move_to_dead_letter_sets_queue_status_failed(async_session):
    """move_to_dead_letter() creates failed_refinements and sets status='failed'."""
    # Setup
    raw = RawMemory(source="api", raw_text="test")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id, status="processing", attempts=3)
    async_session.add(queue)
    await async_session.commit()

    # Move to dead letter
    await move_to_dead_letter(
        async_session,
        queue,
        "Test error reason",
        last_output="test output",
    )
    await async_session.commit()

    # Verify queue status
    queue_check = await async_session.get(RefinementQueue, queue.id)
    assert queue_check.status == "failed"

    # Verify failed_refinements row
    dead_letter_result = await async_session.execute(
        select(FailedRefinement).where(FailedRefinement.queue_id == queue.id)
    )
    dead_letters = dead_letter_result.scalars().all()
    assert len(dead_letters) == 1
    assert dead_letters[0].error_reason == "Test error reason"
    assert dead_letters[0].last_output == "test output"
    assert dead_letters[0].attempt_count == 3


# ── CP 3.5 Observability tests ────────────────────────────────────────────
#
# Covers: worker_heartbeat, ingestion_complete, ingestion_dead_letter,
#         and queue_depth enrichment on exception logs.
#
# Pattern: structlog.testing.capture_logs() captures all structlog events
# emitted inside the `with` block regardless of log level.


# ── A. _get_queue_depth helper ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_queue_depth_empty_queue(async_session):
    """_get_queue_depth() returns zeros when queue is empty."""
    depth = await _get_queue_depth(async_session)
    assert depth == {"pending": 0, "processing": 0}


@pytest.mark.asyncio
async def test_get_queue_depth_counts_pending_and_processing(async_session):
    """_get_queue_depth() returns correct counts for pending and processing rows."""
    raw = RawMemory(source="api", raw_text="x")
    async_session.add(raw)
    await async_session.flush()

    async_session.add(RefinementQueue(raw_id=raw.id, status="pending"))
    async_session.add(RefinementQueue(raw_id=raw.id, status="pending"))
    async_session.add(RefinementQueue(raw_id=raw.id, status="processing"))
    await async_session.flush()

    depth = await _get_queue_depth(async_session)
    assert depth["pending"] == 2
    assert depth["processing"] == 1


# ── B. worker_heartbeat (via run()) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_heartbeat_emitted_on_run_iteration(async_session):
    """run() emits worker_heartbeat at the start of each polling iteration."""
    from src.pipeline import worker as worker_mod

    worker_mod._shutdown.clear()

    async def mock_sleep(_):
        worker_mod._shutdown.set()

    @asynccontextmanager
    async def mock_get_db():
        yield async_session

    mock_anthropic = AsyncMock()
    mock_voyage = AsyncMock()

    with capture_logs() as cap:
        with patch("src.pipeline.worker.get_db", side_effect=mock_get_db):
            with patch("src.pipeline.worker.asyncio.sleep", mock_sleep):
                with patch("src.pipeline.worker.signal.signal"):
                    await worker_mod.run(mock_anthropic, mock_voyage)

    heartbeats = [e for e in cap if e["event"] == "worker_heartbeat"]
    assert len(heartbeats) >= 1
    assert heartbeats[0]["pending"] == 0
    assert heartbeats[0]["processing"] == 0
    assert "poll_interval" in heartbeats[0]


@pytest.mark.asyncio
async def test_heartbeat_fires_on_every_iteration(async_session):
    """run() emits worker_heartbeat once per loop iteration."""
    from src.pipeline import worker as worker_mod

    worker_mod._shutdown.clear()
    call_count = 0

    async def mock_sleep(_):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            worker_mod._shutdown.set()

    @asynccontextmanager
    async def mock_get_db():
        yield async_session

    mock_anthropic = AsyncMock()
    mock_voyage = AsyncMock()

    with capture_logs() as cap:
        with patch("src.pipeline.worker.get_db", side_effect=mock_get_db):
            with patch("src.pipeline.worker.asyncio.sleep", mock_sleep):
                with patch("src.pipeline.worker.signal.signal"):
                    await worker_mod.run(mock_anthropic, mock_voyage)

    heartbeats = [e for e in cap if e["event"] == "worker_heartbeat"]
    assert len(heartbeats) == 2


# ── C. ingestion_complete ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingestion_complete_emitted_on_success(async_session):
    """process_job() emits ingestion_complete with raw_id, attempts, duration_ms on success."""
    raw = RawMemory(source="api", raw_text="test content")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id, status="processing", attempts=1)
    async_session.add(queue)
    await async_session.commit()

    mock_anthropic = AsyncMock()
    mock_anthropic.complete.return_value = '{"type": "memory", "content": "test"}'
    mock_voyage = AsyncMock()
    mock_voyage.embed.return_value = [0.1] * 1024

    @asynccontextmanager
    async def mock_get_db():
        yield async_session

    with capture_logs() as cap:
        with patch("src.pipeline.worker.get_db", return_value=mock_get_db()):
            await process_job(queue, mock_anthropic, mock_voyage)

    events = [e for e in cap if e["event"] == "ingestion_complete"]
    assert len(events) == 1
    assert events[0]["raw_id"] == str(raw.id)
    assert events[0]["attempts"] == 1
    assert "duration_ms" in events[0]


@pytest.mark.asyncio
async def test_ingestion_complete_duration_ms_non_negative(async_session):
    """ingestion_complete duration_ms is a non-negative integer."""
    raw = RawMemory(source="api", raw_text="test content")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id, status="processing", attempts=1)
    async_session.add(queue)
    await async_session.commit()

    mock_anthropic = AsyncMock()
    mock_anthropic.complete.return_value = '{"type": "memory", "content": "test"}'
    mock_voyage = AsyncMock()
    mock_voyage.embed.return_value = [0.1] * 1024

    @asynccontextmanager
    async def mock_get_db():
        yield async_session

    with capture_logs() as cap:
        with patch("src.pipeline.worker.get_db", return_value=mock_get_db()):
            await process_job(queue, mock_anthropic, mock_voyage)

    events = [e for e in cap if e["event"] == "ingestion_complete"]
    assert len(events) == 1
    assert isinstance(events[0]["duration_ms"], int)
    assert events[0]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_ingestion_complete_not_emitted_on_dead_letter(async_session):
    """process_job() does NOT emit ingestion_complete when job moves to dead letter."""
    raw = RawMemory(source="api", raw_text="test content")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id, status="processing", attempts=3)
    async_session.add(queue)
    await async_session.commit()

    mock_anthropic = AsyncMock()
    mock_anthropic.complete.side_effect = ExtractionFailed("permanent failure")
    mock_voyage = AsyncMock()

    @asynccontextmanager
    async def mock_get_db():
        yield async_session

    with capture_logs() as cap:
        with patch("src.pipeline.worker.get_db", return_value=mock_get_db()):
            await process_job(queue, mock_anthropic, mock_voyage)

    assert not any(e["event"] == "ingestion_complete" for e in cap)


@pytest.mark.asyncio
async def test_ingestion_complete_not_emitted_on_retry(async_session):
    """process_job() does NOT emit ingestion_complete when job resets to pending (retry path)."""
    raw = RawMemory(source="api", raw_text="test content")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id, status="processing", attempts=1)
    async_session.add(queue)
    await async_session.commit()

    mock_anthropic = AsyncMock()
    mock_anthropic.complete.side_effect = ExtractionFailed("transient failure")
    mock_voyage = AsyncMock()

    @asynccontextmanager
    async def mock_get_db():
        yield async_session

    with capture_logs() as cap:
        with patch("src.pipeline.worker.get_db", return_value=mock_get_db()):
            await process_job(queue, mock_anthropic, mock_voyage)

    assert not any(e["event"] == "ingestion_complete" for e in cap)
    assert not any(e["event"] == "ingestion_dead_letter" for e in cap)


# ── D. ingestion_dead_letter ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dead_letter_log_emitted(async_session):
    """move_to_dead_letter() emits ingestion_dead_letter log event."""
    raw = RawMemory(source="api", raw_text="x")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id, status="processing", attempts=3)
    async_session.add(queue)
    await async_session.commit()

    with capture_logs() as cap:
        await move_to_dead_letter(async_session, queue, "extraction_failed")

    events = [e for e in cap if e["event"] == "ingestion_dead_letter"]
    assert len(events) == 1
    assert events[0]["raw_id"] == str(raw.id)
    assert events[0]["attempts"] == 3


@pytest.mark.asyncio
async def test_dead_letter_log_not_emitted_on_first_attempt(async_session):
    """process_job() does NOT emit ingestion_dead_letter when attempts=1 (retry path)."""
    raw = RawMemory(source="api", raw_text="x")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id, status="processing", attempts=1)
    async_session.add(queue)
    await async_session.commit()

    mock_anthropic = AsyncMock()
    mock_anthropic.complete.side_effect = ExtractionFailed("transient")
    mock_voyage = AsyncMock()

    @asynccontextmanager
    async def mock_get_db():
        yield async_session

    with capture_logs() as cap:
        with patch("src.pipeline.worker.get_db", return_value=mock_get_db()):
            await process_job(queue, mock_anthropic, mock_voyage)

    assert not any(e["event"] == "ingestion_dead_letter" for e in cap)


@pytest.mark.asyncio
async def test_dead_letter_log_not_emitted_on_second_attempt(async_session):
    """process_job() does NOT emit ingestion_dead_letter when attempts=2 (retry path)."""
    raw = RawMemory(source="api", raw_text="x")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id, status="processing", attempts=2)
    async_session.add(queue)
    await async_session.commit()

    mock_anthropic = AsyncMock()
    mock_anthropic.complete.side_effect = ExtractionFailed("transient")
    mock_voyage = AsyncMock()

    @asynccontextmanager
    async def mock_get_db():
        yield async_session

    with capture_logs() as cap:
        with patch("src.pipeline.worker.get_db", return_value=mock_get_db()):
            await process_job(queue, mock_anthropic, mock_voyage)

    assert not any(e["event"] == "ingestion_dead_letter" for e in cap)


@pytest.mark.asyncio
async def test_dead_letter_log_contains_max_attempts_from_settings(async_session):
    """ingestion_dead_letter includes max_attempts from settings.dead_letter_retry_limit."""
    from src.core.config import settings

    raw = RawMemory(source="api", raw_text="x")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id, status="processing", attempts=3)
    async_session.add(queue)
    await async_session.commit()

    with capture_logs() as cap:
        await move_to_dead_letter(async_session, queue, "reason")

    events = [e for e in cap if e["event"] == "ingestion_dead_letter"]
    assert len(events) == 1
    assert events[0]["max_attempts"] == settings.dead_letter_retry_limit


@pytest.mark.asyncio
async def test_dead_letter_log_contains_error_reason(async_session):
    """ingestion_dead_letter includes the exact error_reason string."""
    raw = RawMemory(source="api", raw_text="x")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id, status="processing", attempts=3)
    async_session.add(queue)
    await async_session.commit()

    with capture_logs() as cap:
        await move_to_dead_letter(
            async_session, queue, "Extraction failed after 3 attempts: bad JSON"
        )

    events = [e for e in cap if e["event"] == "ingestion_dead_letter"]
    assert len(events) == 1
    assert events[0]["error_reason"] == "Extraction failed after 3 attempts: bad JSON"


@pytest.mark.asyncio
async def test_dead_letter_log_emitted_when_attempts_above_limit(async_session):
    """ingestion_dead_letter is emitted even when attempts > dead_letter_retry_limit.

    Edge case: stale lock reclaim can push attempts above 3. The >= 3 check
    ensures dead letter fires for any over-limit attempt count.
    """
    raw = RawMemory(source="api", raw_text="x")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id, status="processing", attempts=4)
    async_session.add(queue)
    await async_session.commit()

    mock_anthropic = AsyncMock()
    mock_anthropic.complete.side_effect = ExtractionFailed("still failing")
    mock_voyage = AsyncMock()

    @asynccontextmanager
    async def mock_get_db():
        yield async_session

    with capture_logs() as cap:
        with patch("src.pipeline.worker.get_db", return_value=mock_get_db()):
            await process_job(queue, mock_anthropic, mock_voyage)

    events = [e for e in cap if e["event"] == "ingestion_dead_letter"]
    assert len(events) == 1
    assert events[0]["attempts"] == 4


# ── E. Exception log queue_depth enrichment ───────────────────────────────


@pytest.mark.asyncio
async def test_exception_log_enriched_with_queue_depth(async_session):
    """process_job() exception logs include queue_depth when extraction fails."""
    raw = RawMemory(source="api", raw_text="x")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id, status="processing", attempts=1)
    async_session.add(queue)
    await async_session.commit()

    mock_anthropic = AsyncMock()
    mock_anthropic.complete.side_effect = ExtractionFailed("transient")
    mock_voyage = AsyncMock()

    @asynccontextmanager
    async def mock_get_db():
        yield async_session

    with capture_logs() as cap:
        with patch("src.pipeline.worker.get_db", return_value=mock_get_db()):
            await process_job(
                queue, mock_anthropic, mock_voyage, queue_depth={"pending": 5, "processing": 2}
            )

    warning_events = [e for e in cap if e.get("event") == "process_job_extraction_failed"]
    assert len(warning_events) == 1
    assert "queue_depth" in warning_events[0]


@pytest.mark.asyncio
async def test_exception_log_queue_depth_matches_passed_value(async_session):
    """process_job() logs the exact queue_depth dict passed in."""
    raw = RawMemory(source="api", raw_text="x")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id, status="processing", attempts=1)
    async_session.add(queue)
    await async_session.commit()

    mock_anthropic = AsyncMock()
    mock_anthropic.complete.side_effect = ExtractionFailed("transient")
    mock_voyage = AsyncMock()

    @asynccontextmanager
    async def mock_get_db():
        yield async_session

    specific_depth = {"pending": 7, "processing": 3}
    with capture_logs() as cap:
        with patch("src.pipeline.worker.get_db", return_value=mock_get_db()):
            await process_job(queue, mock_anthropic, mock_voyage, queue_depth=specific_depth)

    warning_events = [e for e in cap if e.get("event") == "process_job_extraction_failed"]
    assert len(warning_events) == 1
    assert warning_events[0]["queue_depth"] == specific_depth


# ── Task extraction gating ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_memory_item_skips_tasks_for_auto_capture_source(async_session):
    """store_memory_item() does NOT create Task rows for auto-capture sources."""
    raw = RawMemory(source="claude_code_memory", raw_text="session work")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id)
    async_session.add(queue)
    await async_session.flush()

    extraction = ExtractionResult(
        type="memory",
        content="did some refactoring",
        tasks=[TaskExtract(description="refactor component")],
    )
    embedding = [0.1] * 1024

    await store_memory_item(async_session, raw, queue, extraction, embedding, [])

    # No tasks should be created
    task_result = await async_session.execute(select(Task))
    assert task_result.scalars().all() == []


@pytest.mark.asyncio
async def test_store_memory_item_creates_tasks_for_intentional_source(async_session):
    """store_memory_item() creates Task rows for non-auto-capture sources."""
    raw = RawMemory(source="discord", raw_text="need to buy groceries")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id)
    async_session.add(queue)
    await async_session.flush()

    extraction = ExtractionResult(
        type="memory",
        content="grocery reminder",
        tasks=[TaskExtract(description="buy groceries")],
    )
    embedding = [0.1] * 1024

    await store_memory_item(async_session, raw, queue, extraction, embedding, [])

    task_result = await async_session.execute(select(Task))
    tasks = task_result.scalars().all()
    assert len(tasks) == 1
    assert tasks[0].description == "buy groceries"


@pytest.mark.asyncio
async def test_process_job_caps_importance_for_all_auto_capture_sources(async_session):
    """process_job() caps importance for claude_code_memory (not just 'claude-code')."""
    raw = RawMemory(source="claude_code_memory", raw_text="project notes")
    async_session.add(raw)
    await async_session.flush()

    queue = RefinementQueue(raw_id=raw.id, status="processing", attempts=1)
    async_session.add(queue)
    await async_session.commit()

    mock_anthropic = AsyncMock()
    mock_anthropic.complete.return_value = (
        '{"type": "memory", "content": "project notes", "base_importance": 0.9}'
    )
    mock_voyage = AsyncMock()
    mock_voyage.embed.return_value = [0.1] * 1024

    @asynccontextmanager
    async def mock_get_db():
        yield async_session

    with patch("src.pipeline.worker.get_db", return_value=mock_get_db()):
        await process_job(queue, mock_anthropic, mock_voyage)

    result = await async_session.execute(select(MemoryItem).where(MemoryItem.raw_id == raw.id))
    item = result.scalar_one()
    assert item.base_importance <= 0.4
