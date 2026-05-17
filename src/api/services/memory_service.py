"""Business logic for raw memory ingestion.

Extracted from src/api/routes/memory.py so that routes other than
POST /v1/memory (e.g. POST /v1/voice/command) can reuse the same
dedup + RawMemory + RefinementQueue insert path without duplicating it.
"""

from __future__ import annotations

import hashlib
import uuid as _uuid
from dataclasses import dataclass, field
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


@dataclass
class NeighborEntry:
    """One neighbor item returned by expand_memory."""

    memory_id: str
    content: str
    created_at: datetime
    source: str | None


@dataclass
class ExpandResult:
    """Result of an expand_memory call."""

    memory_id: str
    content: str
    raw_text: str | None
    neighbors: list[NeighborEntry] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryItemNotFound(Exception):
    """Raised when memory_expand is called with a missing or superseded id."""


def content_hash(text: str) -> str:
    """SHA-256 hash of normalized text (lowercase + collapsed whitespace)."""
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()


def _as_utc_timestamp(dt: datetime) -> float:
    """Return ``dt`` as a UTC POSIX timestamp, tolerating naive datetimes.

    SQLite stores ``DateTime`` values as naive strings while Postgres stores
    them tz-aware. Tests mix the two within one session, so subtracting them
    raises ``TypeError``. Coerce both sides to UTC before differencing.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC).timestamp()
    return dt.timestamp()


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


async def expand_memory(
    session: AsyncSession,
    *,
    memory_id: str,
) -> ExpandResult:
    """Return full content for a MemoryItem plus its parent + nearby neighbors.

    Used by the tier-2 progressive disclosure flow: when a search hit looks
    relevant but the snippet is truncated, the caller expands it to read the
    full content, its raw provenance, and a handful of sibling items from the
    same source captured close in time.

    The neighbor query fetches up to 3 older + 3 newer non-superseded
    MemoryItems with the same ``source`` as the parent RawMemory, then picks
    the 3 absolute-nearest by ``created_at`` distance in Python. This avoids
    Postgres-only ``EXTRACT(EPOCH FROM ...)`` arithmetic so the same code
    runs under SQLite in tests.

    Args:
        session: Async DB session.
        memory_id: UUID string of the MemoryItem to expand.

    Returns:
        ExpandResult with full content, parent raw_text (or None), neighbors,
        and a metadata dict (source, project, tags, importance_score,
        created_at).

    Raises:
        SupersedesInvalidUUID: memory_id is not a valid UUID.
        MemoryItemNotFound: memory_id missing or is_superseded=True.
    """
    try:
        target_uuid = _uuid.UUID(memory_id)
    except ValueError as exc:
        raise SupersedesInvalidUUID("memory_id is not a valid UUID") from exc

    item = await session.get(MemoryItem, target_uuid)
    if item is None or item.is_superseded:
        raise MemoryItemNotFound(f"MemoryItem {memory_id} not found")

    raw = await session.get(RawMemory, item.raw_id)
    raw_text = raw.raw_text if raw is not None else None
    source = raw.source if raw is not None else None

    neighbors: list[NeighborEntry] = []
    if raw is not None:
        # Fetch up to 3 older and 3 newer same-source neighbors, then pick
        # the 3 absolute-closest by created_at distance in Python.
        older_stmt = (
            select(MemoryItem, RawMemory.source)
            .join(RawMemory, MemoryItem.raw_id == RawMemory.id)
            .where(RawMemory.source == raw.source)
            .where(MemoryItem.is_superseded == False)  # noqa: E712
            .where(MemoryItem.id != item.id)
            .where(MemoryItem.created_at < item.created_at)
            .order_by(MemoryItem.created_at.desc())
            .limit(3)
        )
        newer_stmt = (
            select(MemoryItem, RawMemory.source)
            .join(RawMemory, MemoryItem.raw_id == RawMemory.id)
            .where(RawMemory.source == raw.source)
            .where(MemoryItem.is_superseded == False)  # noqa: E712
            .where(MemoryItem.id != item.id)
            .where(MemoryItem.created_at > item.created_at)
            .order_by(MemoryItem.created_at.asc())
            .limit(3)
        )

        older_rows = (await session.execute(older_stmt)).all()
        newer_rows = (await session.execute(newer_stmt)).all()
        candidates = list(older_rows) + list(newer_rows)

        target_ts = _as_utc_timestamp(item.created_at)

        def _delta_seconds(row: Any) -> float:
            neighbor: MemoryItem = row[0]
            return abs(_as_utc_timestamp(neighbor.created_at) - target_ts)

        candidates.sort(key=_delta_seconds)
        for row in candidates[:3]:
            neighbor: MemoryItem = row[0]
            n_source: str | None = row[1]
            neighbors.append(
                NeighborEntry(
                    memory_id=str(neighbor.id),
                    content=neighbor.content,
                    created_at=neighbor.created_at,
                    source=n_source,
                )
            )

    metadata: dict[str, Any] = {
        "source": source,
        "project": item.project,
        "tags": list(item.tags) if item.tags else [],
        "importance_score": (
            float(item.importance_score) if item.importance_score is not None else None
        ),
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }

    logger.info(
        "memory_expanded",
        memory_id=str(item.id),
        neighbor_count=len(neighbors),
        has_raw=raw is not None,
    )
    return ExpandResult(
        memory_id=str(item.id),
        content=item.content,
        raw_text=raw_text,
        neighbors=neighbors,
        metadata=metadata,
    )
