"""Business logic for raw memory ingestion.

Extracted from src/api/routes/memory.py so that routes other than
POST /v1/memory (e.g. POST /v1/voice/command) can reuse the same
dedup + RawMemory + RefinementQueue insert path without duplicating it.
"""

from __future__ import annotations

import hashlib
import uuid as _uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import MemoryItem, RawMemory, RefinementQueue

logger = structlog.get_logger(__name__)


class SupersedesNotFound(Exception):
    """Raised when supersedes_id points at a MemoryItem that does not exist."""


class SupersedesInvalidUUID(Exception):
    """Raised when supersedes_id is not a valid UUID string."""


@dataclass
class IngestResult:
    """Result of an ingest_memory call."""

    raw_id: str
    status: str  # "queued" | "duplicate"
    supersedes_id: str | None = None


def content_hash(text: str) -> str:
    """SHA-256 hash of normalized text (lowercase + collapsed whitespace)."""
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()


async def ingest_memory(
    session: AsyncSession,
    *,
    text: str,
    source: str,
    metadata: dict[str, Any] | None = None,
    supersedes_id: str | None = None,
) -> IngestResult:
    """Insert a raw_memory row and enqueue it for refinement.

    Runs a 24h dedup window on the SHA-256 content hash. If an existing
    RawMemory matches, returns its id with status="duplicate" and creates
    no new rows.

    Otherwise inserts RawMemory + RefinementQueue atomically and commits.

    Args:
        session: Async DB session (caller owns the lifecycle).
        text: Raw input text to ingest.
        source: Source tag (e.g. "api", "voice", "ios-shortcut").
        metadata: Optional dict; caller is responsible for size validation.
        supersedes_id: Optional UUID of a MemoryItem this ingestion replaces.

    Returns:
        IngestResult with raw_id, status, and echoed supersedes_id.

    Raises:
        SupersedesInvalidUUID: supersedes_id is not a valid UUID.
        SupersedesNotFound: supersedes_id does not match any MemoryItem.
    """
    hash_value = content_hash(text)
    window_start = datetime.now(UTC) - timedelta(hours=24)

    result = await session.execute(
        select(RawMemory)
        .where(RawMemory.content_hash == hash_value)
        .where(RawMemory.created_at >= window_start)
        .limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        logger.info(
            "memory_duplicate_skipped",
            raw_id=str(existing.id),
            content_hash=hash_value,
        )
        return IngestResult(raw_id=str(existing.id), status="duplicate")

    superseded_item: MemoryItem | None = None
    if supersedes_id is not None:
        try:
            target_uuid = _uuid.UUID(supersedes_id)
        except ValueError as exc:
            raise SupersedesInvalidUUID("supersedes_id is not a valid UUID") from exc
        superseded_item = await session.get(MemoryItem, target_uuid)
        if superseded_item is None:
            raise SupersedesNotFound(f"supersedes_id {supersedes_id} not found")

    merged_metadata: dict[str, Any] | None = metadata
    if supersedes_id is not None:
        merged_metadata = dict(metadata or {})
        merged_metadata["supersedes_memory_id"] = supersedes_id

    raw = RawMemory(
        source=source,
        raw_text=text,
        metadata_=merged_metadata,
        content_hash=hash_value,
    )
    session.add(raw)
    await session.flush()

    if superseded_item is not None:
        superseded_item.is_superseded = True
        await session.flush()

    queue_entry = RefinementQueue(raw_id=raw.id)
    session.add(queue_entry)
    await session.flush()
    await session.commit()

    logger.info(
        "memory_ingested",
        raw_id=str(raw.id),
        source=source,
        supersedes_id=supersedes_id,
    )
    return IngestResult(
        raw_id=str(raw.id),
        status="queued",
        supersedes_id=supersedes_id,
    )
