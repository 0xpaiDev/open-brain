"""Tests for the weekly synthesis job (src/jobs/synthesis.py).

Covers:
  - run_synthesis_job(): full integration on in-memory SQLite
  - SynthesisResult Pydantic schema validation
  - build_synthesis_user_message(): prompt construction

All LLM calls are mocked — no production API is ever called.
Test naming: test_<function>_<scenario> per CLAUDE.md conventions.
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from src.core.models import Entity, MemoryEntityLink, MemoryItem, RawMemory
from src.jobs.synthesis import SynthesisResult, run_synthesis_job
from src.llm.client import AnthropicClient, ExtractionFailed
from src.llm.prompts import build_synthesis_user_message

# ── Fixtures & Helpers ────────────────────────────────────────────────────────


MOCK_SYNTHESIS_JSON = {
    "summary": "A productive week with key architectural decisions.",
    "themes": [{"name": "Architecture", "description": "DB and infra decisions", "memory_count": 2}],
    "decisions": [{"decision": "Use PostgreSQL", "reasoning": "scalability", "entities_involved": ["ProjectX"]}],
    "open_tasks": [{"description": "Set up monitoring", "owner": "Alice", "due_date": None}],
    "key_entities": ["ProjectX", "Alice"],
    "memory_count": 3,
    "date_range": "2026-03-08 to 2026-03-15",
}


def _mock_client(response: dict | None = None) -> AsyncMock:
    """Return an AsyncMock AnthropicClient that returns valid synthesis JSON."""
    client = AsyncMock(spec=AnthropicClient)
    client.complete.return_value = json.dumps(response or MOCK_SYNTHESIS_JSON)
    return client


async def _make_memory(
    session,
    content: str = "test content",
    entity_name: str | None = None,
    created_offset_days: float = 0.0,
    is_superseded: bool = False,
) -> MemoryItem:
    """Create RawMemory → MemoryItem and optionally link an Entity."""
    raw = RawMemory(source="test", raw_text=content)
    session.add(raw)
    await session.flush()

    created_at = datetime.now(UTC) - timedelta(days=created_offset_days)
    item = MemoryItem(
        raw_id=raw.id,
        type="memory",
        content=content,
        summary=content[:50],
        embedding=[0.0] * 1024,
        base_importance=0.7,
        is_superseded=is_superseded,
        created_at=created_at,
    )
    session.add(item)
    await session.flush()

    if entity_name:
        entity = Entity(name=entity_name, type="project")
        session.add(entity)
        await session.flush()
        link = MemoryEntityLink(memory_id=item.id, entity_id=entity.id)
        session.add(link)
        await session.flush()

    return item


# ── run_synthesis_job tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_synthesis_job_empty_db_returns_skipped(async_session) -> None:
    """Empty DB: job returns skipped=True without calling the LLM."""
    client = _mock_client()
    result = await run_synthesis_job(async_session, client, days=7)

    assert result["skipped"] is True
    assert result["memory_count"] == 0
    assert result["synthesis_id"] is None
    client.complete.assert_not_called()


@pytest.mark.asyncio
async def test_run_synthesis_job_creates_raw_memory_row(async_session) -> None:
    """A synthesis RawMemory row is created with source='synthesis'."""
    await _make_memory(async_session, "We chose PostgreSQL")
    await async_session.commit()

    await run_synthesis_job(async_session, _mock_client(), days=7)

    rows = await async_session.execute(select(RawMemory).where(RawMemory.source == "synthesis"))
    synthesis_raws = list(rows.scalars().all())
    assert len(synthesis_raws) == 1
    assert synthesis_raws[0].metadata_["is_synthesis"] is True


@pytest.mark.asyncio
async def test_run_synthesis_job_creates_memory_item_row(async_session) -> None:
    """A synthesis MemoryItem is created with type='context' linked to a synthesis RawMemory."""
    await _make_memory(async_session, "Key decision made")
    await async_session.commit()

    await run_synthesis_job(async_session, _mock_client(), days=7)

    # Find MemoryItems linked to synthesis RawMemory rows
    rows = await async_session.execute(
        select(MemoryItem)
        .join(RawMemory, MemoryItem.raw_id == RawMemory.id)
        .where(RawMemory.source == "synthesis")
    )
    items = list(rows.scalars().all())
    assert len(items) == 1
    assert items[0].type == "context"
    assert float(items[0].base_importance) == 0.8


@pytest.mark.asyncio
async def test_run_synthesis_job_returns_synthesis_id(async_session) -> None:
    """Return dict contains a valid UUID string for synthesis_id."""
    await _make_memory(async_session, "Decision note")
    await async_session.commit()

    result = await run_synthesis_job(async_session, _mock_client(), days=7)

    assert result["synthesis_id"] is not None
    UUID(result["synthesis_id"])  # raises if not a valid UUID


@pytest.mark.asyncio
async def test_run_synthesis_job_returns_correct_memory_count(async_session) -> None:
    """Return dict reflects the number of memories passed to the LLM."""
    for i in range(3):
        await _make_memory(async_session, f"Memory {i}")
    await async_session.commit()

    result = await run_synthesis_job(async_session, _mock_client(), days=7)
    assert result["memory_count"] == 3


@pytest.mark.asyncio
async def test_run_synthesis_job_respects_days_window(async_session) -> None:
    """Memories older than the window are excluded."""
    await _make_memory(async_session, "Old memory", created_offset_days=10)
    await _make_memory(async_session, "Recent memory", created_offset_days=3)
    await async_session.commit()

    result = await run_synthesis_job(async_session, _mock_client(), days=7)
    assert result["memory_count"] == 1


@pytest.mark.asyncio
async def test_run_synthesis_job_excludes_superseded(async_session) -> None:
    """Superseded memories are not included in the synthesis window."""
    await _make_memory(async_session, "Superseded", is_superseded=True)
    await _make_memory(async_session, "Active memory")
    await async_session.commit()

    result = await run_synthesis_job(async_session, _mock_client(), days=7)
    assert result["memory_count"] == 1


@pytest.mark.asyncio
async def test_run_synthesis_job_respects_max_limit(async_session, monkeypatch) -> None:
    """Memory count sent to LLM is capped at synthesis_max_memories_per_report."""
    from src.core import config as _config
    new_settings = _config.Settings()
    new_settings = new_settings.model_copy(update={"synthesis_max_memories_per_report": 3})
    monkeypatch.setattr(_config, "settings", new_settings)

    for i in range(5):
        await _make_memory(async_session, f"Memory {i}")
    await async_session.commit()

    client = _mock_client()
    await run_synthesis_job(async_session, client, days=7)

    # The user_content passed to Claude should reference at most 3 memories
    call_kwargs = client.complete.call_args.kwargs
    user_content = call_kwargs["user_content"]
    # Count [1], [2], [3] style markers — there should be at most 3
    import re
    markers = re.findall(r"\[\d+\]", user_content)
    assert len(markers) <= 3


@pytest.mark.asyncio
async def test_run_synthesis_job_llm_failure_propagates(async_session) -> None:
    """ExtractionFailed from the LLM call is re-raised to the caller."""
    await _make_memory(async_session, "Some memory")
    await async_session.commit()

    client = AsyncMock(spec=AnthropicClient)
    client.complete.side_effect = RuntimeError("API down")

    with pytest.raises(ExtractionFailed):
        await run_synthesis_job(async_session, client, days=7)


@pytest.mark.asyncio
async def test_run_synthesis_job_commit_persists_to_db(async_session, async_engine) -> None:
    """Committed synthesis row survives session close (flush alone would not)."""
    await _make_memory(async_session, "Important decision")
    await async_session.commit()

    result = await run_synthesis_job(async_session, _mock_client(), days=7)
    synthesis_id = result["synthesis_id"]

    # Open a fresh session and query
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as fresh_session:
        rows = await fresh_session.execute(
            select(MemoryItem).where(MemoryItem.id == UUID(synthesis_id))
        )
        item = rows.scalar_one_or_none()
    assert item is not None
    assert item.type == "context"


# ── SynthesisResult schema tests ─────────────────────────────────────────────


def test_synthesis_result_validates_correct_schema() -> None:
    """A valid synthesis dict produces a SynthesisResult without error."""
    result = SynthesisResult(**MOCK_SYNTHESIS_JSON)
    assert result.summary.startswith("A productive week")
    assert len(result.themes) == 1
    assert result.memory_count == 3


def test_synthesis_result_rejects_missing_summary() -> None:
    """SynthesisResult requires summary field."""
    bad = {k: v for k, v in MOCK_SYNTHESIS_JSON.items() if k != "summary"}
    with pytest.raises(ValidationError):
        SynthesisResult(**bad)


# ── build_synthesis_user_message tests ───────────────────────────────────────


def test_build_synthesis_user_message_uses_delimiters() -> None:
    """Output is wrapped in <user_input> tags for prompt injection defense."""
    msg = build_synthesis_user_message(
        [{"type": "memory", "content": "test", "summary": "s", "entities": []}],
        "2026-03-08",
        "2026-03-15",
    )
    assert "<user_input>" in msg
    assert "</user_input>" in msg


def test_build_synthesis_user_message_includes_entity_names() -> None:
    """Entity names are present in the user message for Claude's entity context."""
    msg = build_synthesis_user_message(
        [{"type": "memory", "content": "test", "summary": "s", "entities": ["ProjectAlpha"]}],
        "2026-03-08",
        "2026-03-15",
    )
    assert "ProjectAlpha" in msg
