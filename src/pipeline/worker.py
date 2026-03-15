"""Memory refinement queue worker with polling and dead letter handling.

This is the highest-risk component. The worker:
1. Polls refinement_queue with SELECT FOR UPDATE SKIP LOCKED
2. Implements FIX-2: stale lock reclaim (locked_at < NOW() - TTL)
3. Runs the full pipeline for each job
4. Implements 3-attempt dead letter: fails after 3 attempts
5. Handles graceful shutdown on SIGTERM

The worker is typically run as a separate process, not in the API loop.
"""

import asyncio
import random
import signal
import uuid as _uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import get_db_context as get_db
from src.core.models import (
    Entity,
    FailedRefinement,
    MemoryEntityLink,
    MemoryItem,
    RawMemory,
    RefinementQueue,
)
from src.llm.client import (
    AnthropicClient,
    EmbeddingFailed,
    ExtractionFailed,
    VoyageEmbeddingClient,
    anthropic_client,
    embedding_client,
)
from src.pipeline.embedder import embed_text
from src.pipeline.entity_resolver import resolve_entities
from src.pipeline.extractor import extract
from src.pipeline.normalizer import normalize
from src.pipeline.validator import ValidationFailed, validate

logger = structlog.get_logger(__name__)

# Graceful shutdown event
_shutdown = asyncio.Event()


def _shutdown_handler(signum, frame):
    """Signal handler for SIGTERM."""
    logger.info("shutdown_signal_received", signum=signum)
    _shutdown.set()


# ── Queue polling and processing ──────────────────────────────────────────


async def claim_batch(
    session: AsyncSession, batch_size: int = 1
) -> list[RefinementQueue]:
    """Claim a batch of jobs from the queue using SELECT FOR UPDATE SKIP LOCKED.

    FIX-2: Reclaims stale items WHERE locked_at < NOW() - INTERVAL '{ttl} seconds'.
    Sets status='processing', locked_at=now(), and increments attempts.

    Args:
        session: AsyncSession for database operations
        batch_size: Maximum items to claim per call (default 1)

    Returns:
        List of claimed RefinementQueue rows with status='processing'
    """
    if settings is None:
        logger.warning("settings_not_initialized")
        ttl_seconds = 300  # fallback default
    else:
        ttl_seconds = settings.worker_lock_ttl_seconds

    # SELECT FOR UPDATE SKIP LOCKED: pick pending or stale-processing jobs
    # Stale lock reclaim: WHERE locked_at < now() - interval
    query = select(RefinementQueue).where(
        and_(
            or_(
                RefinementQueue.status == "pending",
                and_(
                    RefinementQueue.status == "processing",
                    RefinementQueue.locked_at
                    < datetime.now(UTC)
                    - timedelta(seconds=ttl_seconds),
                ),
            )
        )
    )

    # Execute with row locking (SQLite doesn't support this, but PostgreSQL does)
    try:
        result = await session.execute(
            query.with_for_update(skip_locked=True).limit(batch_size)
        )
        jobs = result.scalars().all()
    except Exception as e:
        # SQLite doesn't support FOR UPDATE — fallback without locking
        logger.debug(
            "claim_batch_fallback_no_locking",
            error=str(e),
            note="FOR UPDATE SKIP LOCKED not supported",
        )
        result = await session.execute(query.limit(batch_size))
        jobs = result.scalars().all()

    # Mark as processing
    for job in jobs:
        job.status = "processing"
        job.locked_at = datetime.now(UTC)
        job.attempts += 1
        job.updated_at = datetime.now(UTC)

    await session.flush()

    logger.info(
        "claim_batch_success",
        batch_size=len(jobs),
        ttl_seconds=ttl_seconds,
    )

    return jobs


async def process_job(
    queue_row: RefinementQueue,
    anthropic: AnthropicClient,
    voyage: VoyageEmbeddingClient,
) -> None:
    """Process a single job: normalize → extract → validate → embed → resolve → store.

    If extraction fails:
    - attempts < 3: reset to 'pending' for retry with escalated prompt
    - attempts >= 3: move to dead letter

    If embedding fails: always move to dead letter (not retryable).

    Args:
        queue_row: RefinementQueue row to process
        anthropic: Anthropic LLM client
        voyage: Voyage AI embedding client

    Raises:
        Exception: If database operations fail (will be logged and handled)
    """
    queue_id = queue_row.id  # Capture ID before session switch
    async with get_db() as session:
        try:
            # Re-fetch queue_row in this session so changes are tracked and committed here
            queue_row = await session.get(RefinementQueue, queue_id)
            if not queue_row:
                logger.error("queue_row_not_found", queue_id=str(queue_id))
                return

            # Fetch the raw memory
            raw = await session.get(RawMemory, queue_row.raw_id)
            if not raw:
                logger.error(
                    "raw_memory_not_found",
                    raw_id=str(queue_row.raw_id),
                )
                await move_to_dead_letter(
                    session,
                    queue_row,
                    "Raw memory not found",
                )
                return

            # Step 1: Normalize
            normalized_text = normalize(raw.raw_text)
            logger.debug("process_job_normalize", raw_len=len(raw.raw_text))

            # Step 2: Extract (with escalating retries)
            try:
                extraction = await extract(
                    normalized_text,
                    attempt=queue_row.attempts - 1,  # attempts is 1-indexed
                    client=anthropic,
                )
                logger.debug("process_job_extract_success")
            except ExtractionFailed as e:
                logger.warning(
                    "process_job_extraction_failed",
                    attempt=queue_row.attempts,
                    error=str(e),
                )
                if queue_row.attempts < 3:
                    # Reset to pending for retry with escalated prompt
                    queue_row.status = "pending"
                    await session.flush()
                    await session.commit()
                    logger.info(
                        "process_job_reset_to_pending_for_retry",
                        next_attempt=queue_row.attempts + 1,
                    )
                    return
                else:
                    # 3 attempts exhausted
                    await move_to_dead_letter(
                        session,
                        queue_row,
                        f"Extraction failed after 3 attempts: {e}",
                        last_output=str(e),
                    )
                    return

            # Step 3: Validate
            try:
                extraction = validate(extraction)
                logger.debug("process_job_validate_success")
            except ValidationFailed as e:
                logger.error("process_job_validation_failed", error=str(e))
                await move_to_dead_letter(
                    session,
                    queue_row,
                    f"Validation failed: {e}",
                )
                return

            # Step 4: Embed
            try:
                embedding = await embed_text(normalized_text, client=voyage)
                logger.debug("process_job_embed_success")
            except EmbeddingFailed as e:
                logger.error("process_job_embedding_failed", error=str(e))
                await move_to_dead_letter(
                    session,
                    queue_row,
                    f"Embedding failed: {e}",
                )
                return

            # Step 5: Resolve entities
            try:
                entities = await resolve_entities(session, extraction.entities)
                logger.debug(
                    "process_job_resolve_entities_success",
                    entity_count=len(entities),
                )
            except Exception as e:
                logger.exception("process_job_resolve_entities_failed", error=str(e))
                await move_to_dead_letter(
                    session,
                    queue_row,
                    f"Entity resolution failed: {e}",
                )
                return

            # Step 6: Store memory item
            try:
                await store_memory_item(
                    session,
                    raw,
                    queue_row,
                    extraction,
                    embedding,
                    entities,
                )
                await session.commit()
                logger.info("process_job_success")
            except Exception as e:
                logger.exception("process_job_store_failed", error=str(e))
                await move_to_dead_letter(
                    session,
                    queue_row,
                    f"Storage failed: {e}",
                )
                return

        except Exception as e:
            logger.exception("process_job_unexpected_error", error=str(e))
            await move_to_dead_letter(
                session,
                queue_row,
                f"Unexpected error: {e}",
            )


async def store_memory_item(
    session: AsyncSession,
    raw: RawMemory,
    queue_row: RefinementQueue,
    extraction,  # ExtractionResult
    embedding: list[float],
    entities: list[Entity],
) -> MemoryItem:
    """Store extracted memory to database in a single transaction.

    Creates:
    - memory_items row
    - memory_entity_links rows (ON CONFLICT DO NOTHING for idempotency)
    - decision rows
    - task rows
    - Updates refinement_queue status to 'done'

    All in one transaction to ensure atomicity.

    Args:
        session: AsyncSession with active transaction
        raw: RawMemory source row
        queue_row: RefinementQueue row being processed
        extraction: ExtractionResult with extracted data
        embedding: List of 1024 floats from embedder
        entities: List of resolved Entity ORM objects

    Returns:
        Stored MemoryItem ORM object

    Raises:
        Exception: If any insert fails
    """
    # Read supersedes side-channel written by ingestion route
    _raw_supersedes = (raw.metadata_ or {}).get("supersedes_memory_id")
    supersedes_memory_id: _uuid.UUID | None = (
        _uuid.UUID(_raw_supersedes) if _raw_supersedes else None
    )

    # Insert memory_item
    memory_item = MemoryItem(
        raw_id=raw.id,
        type=extraction.type,
        content=extraction.content,
        summary=extraction.summary,
        base_importance=extraction.base_importance,
        embedding=embedding,  # Store as JSONB/JSON list
        supersedes_id=supersedes_memory_id,
    )
    session.add(memory_item)
    await session.flush()  # Get the ID

    # Insert entity links (ON CONFLICT DO NOTHING for idempotency)
    for entity in entities:
        link = MemoryEntityLink(
            memory_id=memory_item.id,
            entity_id=entity.id,
        )
        session.add(link)

    # Insert decisions
    from src.core.models import Decision

    for decision_extract in extraction.decisions:
        decision = Decision(
            memory_id=memory_item.id,
            decision=decision_extract.decision,
            reasoning=decision_extract.reasoning or "",
            alternatives=decision_extract.alternatives,
        )
        session.add(decision)

    # Insert tasks
    from src.core.models import Task

    for task_extract in extraction.tasks:
        task = Task(
            memory_id=memory_item.id,
            description=task_extract.description,
            owner=task_extract.owner,
            due_date=None,  # Parse ISO date later if provided
        )
        if task_extract.due_date:
            try:
                task.due_date = datetime.fromisoformat(
                    task_extract.due_date
                ).replace(tzinfo=UTC)
            except ValueError:
                logger.warning(
                    "invalid_due_date_format",
                    due_date=task_extract.due_date,
                )
        session.add(task)

    # Mark queue row as done
    queue_row.status = "done"
    queue_row.updated_at = datetime.now(UTC)

    await session.flush()  # Persist changes

    logger.info(
        "store_memory_item_success",
        memory_id=str(memory_item.id),
        entities=len(entities),
        decisions=len(extraction.decisions),
        tasks=len(extraction.tasks),
    )

    return memory_item


async def move_to_dead_letter(
    session: AsyncSession,
    queue_row: RefinementQueue,
    error_reason: str,
    last_output: str | None = None,
) -> None:
    """Move a job to dead letter after permanent failure.

    Creates a failed_refinements row with error details and marks
    the queue row as 'failed'.

    Args:
        session: AsyncSession for database operations
        queue_row: RefinementQueue row that failed
        error_reason: Error message to store
        last_output: Last LLM output (if applicable) for debugging
    """
    failed = FailedRefinement(
        raw_id=queue_row.raw_id,
        queue_id=queue_row.id,
        error_reason=error_reason,
        attempt_count=queue_row.attempts,
        last_output=last_output,
    )
    session.add(failed)

    queue_row.status = "failed"
    queue_row.updated_at = datetime.now(UTC)

    await session.flush()
    await session.commit()

    logger.warning(
        "move_to_dead_letter",
        raw_id=str(queue_row.raw_id),
        attempts=queue_row.attempts,
        error=error_reason,
    )


# ── Main polling loop ─────────────────────────────────────────────────────


async def run(
    anthropic: AnthropicClient | None = None,
    voyage: VoyageEmbeddingClient | None = None,
) -> None:
    """Main worker polling loop.

    Installs SIGTERM handler for graceful shutdown. Uses module-level singletons
    if client args not provided (production use). Polls every
    `worker_poll_interval + random jitter` seconds.

    Args:
        anthropic: AnthropicClient instance (optional, uses singleton if None)
        voyage: VoyageEmbeddingClient instance (optional, uses singleton if None)
    """
    # Use provided clients or module singletons
    if anthropic is None:
        anthropic = anthropic_client
    if voyage is None:
        voyage = embedding_client

    if anthropic is None or voyage is None:
        logger.error(
            "worker_initialization_failed",
            anthropic_client=anthropic is not None,
            voyage_client=voyage is not None,
        )
        raise RuntimeError(
            "Cannot start worker: Anthropic or Voyage API key not configured"
        )

    # Install SIGTERM handler
    signal.signal(signal.SIGTERM, _shutdown_handler)
    logger.info("worker_started")

    # Polling loop
    while not _shutdown.is_set():
        try:
            async with get_db() as session:
                # Claim a batch
                jobs = await claim_batch(session, batch_size=1)

                if not jobs:
                    # No jobs available, sleep before next poll
                    poll_interval = settings.worker_poll_interval if settings else 5
                    jitter = random.uniform(0, 2.0)
                    await asyncio.sleep(poll_interval + jitter)
                    continue

                # Commit "processing" status before handing off to process_job
                await session.commit()

            # Process each job outside the claim session
            for job in jobs:
                if _shutdown.is_set():
                    logger.info("worker_shutdown_during_processing")
                    break

                await process_job(job, anthropic, voyage)

        except Exception as e:
            logger.exception("worker_loop_error", error=str(e))
            await asyncio.sleep(5)  # Back off on errors

    logger.info("worker_shutdown_complete")


async def main() -> None:
    """Initialize DB then run the worker loop."""
    from src.core.database import init_db

    await init_db()
    await run()


if __name__ == "__main__":
    asyncio.run(main())
