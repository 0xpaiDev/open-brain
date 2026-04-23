"""Sync completed DailyPulse entries into memory_items for hybrid search visibility.

Every pulse that reaches "completed" or "parsed" status produces a corresponding
memory_item so that wellness queries like "how did I sleep last week?" work
through the existing RAG pipeline.
"""

from __future__ import annotations

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import DailyPulse, MemoryItem, RawMemory
from src.pipeline.embedder import embed_text

logger = structlog.get_logger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _format_pulse_content(pulse: DailyPulse) -> str:
    """Build a natural-language string from a pulse for embedding.

    Skips clauses for None fields so the embedding is clean.

    Header depends on signal_type: non-"open" signal types are tagged with the
    signal so the RAG embedding isn't misled into treating a remark as a
    question. Legacy rows (signal_type NULL) and "open" rows keep the original
    "AI question: …" framing for backward compat.
    """
    date_str = pulse.pulse_date.strftime("%Y-%m-%d")
    signal_type = getattr(pulse, "signal_type", None)
    is_question_shape = signal_type in (None, "open")

    if is_question_shape:
        parts = [f"Daily pulse for {date_str}:"]
    else:
        parts = [f"Daily pulse ({signal_type}) for {date_str}:"]

    if pulse.sleep_quality is not None:
        parts.append(f"Sleep quality {pulse.sleep_quality}/5,")
    if pulse.energy_level is not None:
        parts.append(f"energy level {pulse.energy_level}/5,")
    if pulse.wake_time:
        parts.append(f"woke at {pulse.wake_time}.")
    if pulse.notes:
        parts.append(f"Notes: {pulse.notes}")
    if pulse.ai_question and pulse.ai_question_response:
        if is_question_shape:
            parts.append(
                f"AI question: {pulse.ai_question} Response: {pulse.ai_question_response}"
            )
        else:
            parts.append(
                f"Signal remark: {pulse.ai_question} Response: {pulse.ai_question_response}"
            )
    if pulse.clean_meal is not None:
        parts.append(f"Clean eating: {'yes' if pulse.clean_meal else 'no'}.")
    if pulse.alcohol is not None:
        parts.append(f"Alcohol: {'yes' if pulse.alcohol else 'no'}.")

    return " ".join(parts)


# ── Main sync function ──────────────────────────────────────────────────────


async def sync_pulse_to_memory(
    session: AsyncSession,
    pulse: DailyPulse,
    voyage_client,
) -> None:
    """Sync a completed DailyPulse to memory_items.

    1. Format content string from pulse fields
    2. Generate embedding via embed_text()
    3. Find & supersede existing memory_item(s) for this pulse_id
    4. Create RawMemory(source="daily-pulse", metadata_={"pulse_id": str(pulse.id)})
    5. Create MemoryItem(type="daily_pulse", content=..., embedding=..., raw_id=...)
    6. Commit
    """
    pulse_id_str = str(pulse.id)
    content = _format_pulse_content(pulse)

    # Generate embedding
    embedding = await embed_text(content, voyage_client)

    # Find and supersede existing memory_items for this pulse
    existing = await session.execute(
        select(MemoryItem)
        .join(RawMemory, MemoryItem.raw_id == RawMemory.id)
        .where(
            and_(
                RawMemory.metadata_["pulse_id"].as_string() == pulse_id_str,
                MemoryItem.is_superseded.is_(False),
            )
        )
        .order_by(MemoryItem.created_at.desc())
    )
    for old_item in existing.scalars():
        old_item.is_superseded = True

    # Create new raw memory
    raw = RawMemory(
        source="daily-pulse",
        raw_text=content,
        metadata_={"pulse_id": pulse_id_str},
    )
    session.add(raw)
    await session.flush()  # populate raw.id

    # Create new memory item
    memory_item = MemoryItem(
        raw_id=raw.id,
        type="daily_pulse",
        content=content,
        base_importance=0.5,
        embedding=embedding,
    )
    session.add(memory_item)
    await session.commit()

    logger.info(
        "pulse_synced_to_memory",
        pulse_id=pulse_id_str,
        memory_id=str(memory_item.id),
    )
