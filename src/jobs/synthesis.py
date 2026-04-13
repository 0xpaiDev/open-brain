"""Weekly synthesis job for Open Brain.

Fetches memory_items from the last N days, clusters them by shared entities,
calls Claude to produce a structured digest report, and stores the result as a
new MemoryItem with metadata_.is_synthesis=True.

Algorithm
---------
1. Fetch all non-superseded MemoryItems created within the window (ORDER BY
   importance_score DESC, capped at synthesis_max_memories_per_report).
2. Load entity names for each memory in a single bulk join.
3. Build a prompt payload annotating each memory with its entity context.
4. Call Claude (synthesis_model — Haiku for MVP, override to Opus in production).
5. Validate response against SynthesisResult schema.
6. Persist:  RawMemory(source="synthesis") → MemoryItem(metadata_.is_synthesis=True)
7. Commit and return summary dict.

Settings used
-------------
- synthesis_max_memories_per_report (default: 50)
- synthesis_model (default: claude-haiku-4-5-20251001)
- anthropic_api_key

Invocation
----------
    python -m src.jobs.synthesis           # last 7 days (default)
    python -m src.jobs.synthesis --days 14
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.models import Entity, MemoryEntityLink, MemoryItem, RawMemory
from src.llm.client import AnthropicClient, ExtractionFailed
from src.llm.prompts import SYNTHESIS_SYSTEM_PROMPT, build_synthesis_user_message

logger = structlog.get_logger(__name__)


# ── Pydantic models for LLM output ───────────────────────────────────────────


class ThemeEntry(BaseModel):
    """A recurring theme identified across memory items."""

    name: str
    description: str
    memory_count: int = 0


class SynthesisDecision(BaseModel):
    """A decision surfaced during synthesis."""

    decision: str
    reasoning: str | None = None
    entities_involved: list[str] = []


class SynthesisTask(BaseModel):
    """An open task surfaced during synthesis."""

    description: str
    owner: str | None = None
    due_date: str | None = None


class SynthesisResult(BaseModel):
    """Structured output from the synthesis LLM call."""

    summary: str
    themes: list[ThemeEntry] = []
    decisions: list[SynthesisDecision] = []
    open_tasks: list[SynthesisTask] = []
    key_entities: list[str] = []
    memory_count: int = 0
    date_range: str = ""


# ── Internal helpers ──────────────────────────────────────────────────────────


async def _fetch_recent_memories(
    session: AsyncSession,
    cutoff: datetime,
    limit: int,
) -> list[MemoryItem]:
    """Fetch non-superseded MemoryItems created after cutoff, ordered by importance."""
    result = await session.execute(
        select(MemoryItem)
        .where(
            and_(
                MemoryItem.created_at >= cutoff,
                MemoryItem.is_superseded == False,  # noqa: E712
            )
        )
        .order_by(MemoryItem.importance_score.desc().nulls_last())
        .limit(limit)
    )
    return list(result.scalars().all())


async def _load_entity_map(
    session: AsyncSession,
    memory_ids: list,
) -> dict[str, list[str]]:
    """Return {memory_id_str: [entity_name, ...]} for a batch of memory IDs.

    Single bulk join query — avoids N+1.
    """
    if not memory_ids:
        return {}
    rows = await session.execute(
        select(MemoryEntityLink.memory_id, Entity.name)
        .join(Entity, MemoryEntityLink.entity_id == Entity.id)
        .where(MemoryEntityLink.memory_id.in_(memory_ids))
    )
    entity_map: dict[str, list[str]] = {}
    for memory_id, entity_name in rows.all():
        entity_map.setdefault(str(memory_id), []).append(entity_name)
    return entity_map


def _build_memory_dicts(
    memories: list[MemoryItem],
    entity_map: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Convert ORM objects to plain dicts suitable for prompt building."""
    result = []
    for m in memories:
        result.append(
            {
                "id": str(m.id),
                "type": m.type,
                "content": m.content,
                "summary": m.summary or "",
                "entities": entity_map.get(str(m.id), []),
            }
        )
    return result


async def _call_synthesis_llm(
    client: AnthropicClient,
    memory_dicts: list[dict[str, Any]],
    date_from: str,
    date_to: str,
) -> SynthesisResult:
    """Call Claude with the synthesis prompt and validate the response.

    Raises:
        ExtractionFailed: If JSON parsing or schema validation fails.
    """
    user_message = build_synthesis_user_message(memory_dicts, date_from, date_to)

    try:
        response_text = await client.complete(
            system_prompt=SYNTHESIS_SYSTEM_PROMPT,
            user_content=user_message,
            max_tokens=8192,
        )
    except Exception as e:
        raise ExtractionFailed(f"Synthesis LLM call failed: {e}") from e

    # Strip markdown code fences if present
    stripped = response_text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1]
        stripped = stripped.rsplit("```", 1)[0].strip()

    try:
        json_data = json.loads(stripped)
    except json.JSONDecodeError as e:
        logger.exception(
            "synthesis_json_parse_failed", error=str(e), response_text=response_text[:200]
        )
        raise ExtractionFailed(f"Failed to parse synthesis response as JSON: {e}") from e

    try:
        result = SynthesisResult(**json_data)
    except ValueError as e:
        logger.exception("synthesis_schema_validation_failed", error=str(e))
        raise ExtractionFailed(f"Synthesis response does not match schema: {e}") from e

    return result


async def _store_synthesis_report(
    session: AsyncSession,
    result: SynthesisResult,
    date_from: str,
    date_to: str,
) -> MemoryItem:
    """Persist the synthesis report as RawMemory + MemoryItem.

    Step 1: INSERT RawMemory(source="synthesis") for FK compliance.
    Step 2: INSERT MemoryItem with is_synthesis=True in metadata_.
    """
    raw = RawMemory(
        source="synthesis",
        raw_text=result.summary,
        metadata_={"is_synthesis": True, "date_from": date_from, "date_to": date_to},
    )
    session.add(raw)
    await session.flush()

    memory_item = MemoryItem(
        raw_id=raw.id,
        type="context",
        content=json.dumps(result.model_dump()),
        summary=result.summary,
        base_importance=0.8,
    )
    session.add(memory_item)
    await session.flush()

    return memory_item


# ── Public interface ──────────────────────────────────────────────────────────


async def run_synthesis_job(
    session: AsyncSession,
    client: AnthropicClient,
    days: int = 7,
) -> dict[str, Any]:
    """Run one synthesis pass over recent memories.

    Args:
        session: Async SQLAlchemy session. Calls commit() on success.
        client: AnthropicClient instance to use for the synthesis call.
        days: Number of days to look back (default: 7).

    Returns:
        Dict with keys:
          - memory_count (int): memories processed
          - synthesis_id (str | None): UUID of created MemoryItem, None if skipped
          - date_from (str): ISO date string
          - date_to (str): ISO date string
          - skipped (bool): True if no memories found
    """
    settings = get_settings()

    if "haiku" in settings.synthesis_model:
        logger.warning(
            "synthesis_running_with_haiku",
            model=settings.synthesis_model,
            advice="For production quality, set SYNTHESIS_MODEL=claude-opus-4-6",
        )

    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)
    date_from = cutoff.strftime("%Y-%m-%d")
    date_to = now.strftime("%Y-%m-%d")

    memories = await _fetch_recent_memories(
        session,
        cutoff=cutoff,
        limit=settings.synthesis_max_memories_per_report,
    )

    logger.info("synthesis_job_start", memory_count=len(memories), days=days)

    if not memories:
        logger.info("synthesis_job_skipped", reason="no_memories_in_window")
        return {
            "memory_count": 0,
            "synthesis_id": None,
            "date_from": date_from,
            "date_to": date_to,
            "skipped": True,
        }

    memory_ids = [m.id for m in memories]
    entity_map = await _load_entity_map(session, memory_ids)
    memory_dicts = _build_memory_dicts(memories, entity_map)

    synthesis_result = await _call_synthesis_llm(client, memory_dicts, date_from, date_to)

    memory_item = await _store_synthesis_report(session, synthesis_result, date_from, date_to)
    await session.commit()

    duration = round((datetime.now(UTC) - now).total_seconds(), 2)
    logger.info(
        "synthesis_job_complete",
        synthesis_id=str(memory_item.id),
        memory_count=len(memories),
        theme_count=len(synthesis_result.themes),
        duration_seconds=duration,
    )

    return {
        "memory_count": len(memories),
        "synthesis_id": str(memory_item.id),
        "date_from": date_from,
        "date_to": date_to,
        "skipped": False,
    }


async def _synthesis_job(days: int = 7) -> None:
    """Core synthesis job logic (DB init handled by runner)."""
    from src.core.database import get_db_context

    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for synthesis job. Set it in .env.")

    client = AnthropicClient(
        api_key=settings.anthropic_api_key.get_secret_value(),
        model=settings.synthesis_model,
    )

    async with get_db_context() as session:
        result = await run_synthesis_job(session, client, days=days)
        logger.info("synthesis_job_main_complete", **result)


async def main() -> None:
    """Entry point for cron invocation.

    Usage:
        python -m src.jobs.synthesis           # last 7 days
        python -m src.jobs.synthesis --days 14
    """
    import argparse

    from src.jobs.runner import run_tracked

    parser = argparse.ArgumentParser(description="Run weekly synthesis job")
    parser.add_argument("--days", type=int, default=7, help="Days to look back (default: 7)")
    args = parser.parse_args()

    await run_tracked("synthesis", _synthesis_job, days=args.days)


if __name__ == "__main__":
    asyncio.run(main())
