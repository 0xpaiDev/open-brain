"""Tests for the memory refinement queue worker.

CRITICAL TESTS:
- test_claim_batch_reclaims_stale_processing (FIX-2 validation)
- test_3_failure_path_moves_to_dead_letter (FIX-3 validation)

These tests validate the two most critical bug fixes in the worker.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from src.core.models import (
    Entity,
    FailedRefinement,
    MemoryItem,
    RawMemory,
    RefinementQueue,
)
from src.llm.client import ExtractionFailed
from src.pipeline.extractor import EntityExtract, ExtractionResult
from src.pipeline.worker import (
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
    result = await async_session.execute(
        select(MemoryItem).where(MemoryItem.raw_id == raw.id)
    )
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
    memory_item = await store_memory_item(
        async_session, raw, queue, extraction, embedding, []
    )

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
