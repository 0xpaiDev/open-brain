"""Tests for GET /v1/memory/{id}/expand endpoint and expand_memory service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.api.services.memory_service import (
    MemoryItemNotFound,
    SupersedesInvalidUUID,
    expand_memory,
)
from src.core.models import MemoryItem, RawMemory


async def _create_raw(
    session,
    *,
    source: str = "claude-code-session",
    raw_text: str = "raw provenance text",
) -> RawMemory:
    raw = RawMemory(
        source=source,
        raw_text=raw_text,
        content_hash=uuid4().hex,
    )
    session.add(raw)
    await session.flush()
    return raw


async def _create_memory_item(
    session,
    *,
    raw: RawMemory | None = None,
    source: str = "claude-code-session",
    content: str = "full memory content body",
    is_superseded: bool = False,
    created_at: datetime | None = None,
    project: str | None = None,
    tags: list[str] | None = None,
) -> MemoryItem:
    if raw is None:
        raw = await _create_raw(session, source=source)
    item = MemoryItem(
        raw_id=raw.id,
        type="memory",
        content=content,
        summary=None,
        base_importance=0.5,
        dynamic_importance=0.0,
        is_superseded=is_superseded,
        project=project,
        tags=tags,
    )
    if created_at is not None:
        item.created_at = created_at
    session.add(item)
    await session.flush()
    return item


# ── Service-level tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_expand_returns_full_content_and_raw(async_session) -> None:
    """Service returns full content plus the parent raw_text."""
    raw = await _create_raw(async_session, raw_text="original raw transcript")
    item = await _create_memory_item(
        async_session, raw=raw, content="extracted summary", project="open-brain"
    )
    await async_session.commit()

    result = await expand_memory(async_session, memory_id=str(item.id))

    assert result.memory_id == str(item.id)
    assert result.content == "extracted summary"
    assert result.raw_text == "original raw transcript"
    assert result.metadata["source"] == "claude-code-session"
    assert result.metadata["project"] == "open-brain"


@pytest.mark.asyncio
async def test_expand_invalid_uuid_raises(async_session) -> None:
    """Non-UUID memory_id raises SupersedesInvalidUUID."""
    with pytest.raises(SupersedesInvalidUUID):
        await expand_memory(async_session, memory_id="not-a-uuid")


@pytest.mark.asyncio
async def test_expand_missing_raises(async_session) -> None:
    """Unknown memory_id raises MemoryItemNotFound."""
    with pytest.raises(MemoryItemNotFound):
        await expand_memory(async_session, memory_id=str(uuid4()))


@pytest.mark.asyncio
async def test_expand_superseded_raises(async_session) -> None:
    """Superseded item is treated as not-found."""
    item = await _create_memory_item(async_session, is_superseded=True)
    await async_session.commit()

    with pytest.raises(MemoryItemNotFound):
        await expand_memory(async_session, memory_id=str(item.id))


@pytest.mark.asyncio
async def test_expand_returns_nearest_neighbors_same_source(async_session) -> None:
    """Neighbors are picked by absolute time distance from the target, same source."""
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    raw_session = await _create_raw(async_session, source="claude-code-session")
    target = await _create_memory_item(
        async_session, raw=raw_session, content="target", created_at=base
    )

    # 3 older + 3 newer same-source neighbors at varying distances.
    older = []
    for i, delta_h in enumerate([1, 5, 20]):
        n = await _create_memory_item(
            async_session,
            source="claude-code-session",
            content=f"older-{i}",
            created_at=base - timedelta(hours=delta_h),
        )
        older.append(n)
    newer = []
    for i, delta_h in enumerate([2, 10, 30]):
        n = await _create_memory_item(
            async_session,
            source="claude-code-session",
            content=f"newer-{i}",
            created_at=base + timedelta(hours=delta_h),
        )
        newer.append(n)
    # Off-source distractor — must NOT appear in neighbors.
    await _create_memory_item(
        async_session,
        source="api",
        content="off-source",
        created_at=base + timedelta(minutes=5),
    )
    await async_session.commit()

    result = await expand_memory(async_session, memory_id=str(target.id))

    assert len(result.neighbors) == 3
    contents = [n.content for n in result.neighbors]
    # Closest three by absolute distance: older-0 (1h), newer-0 (2h), newer-1 (10h).
    # older-1 is 5h so it must be selected over newer-1 (10h).
    assert "off-source" not in contents
    assert contents[0] in {"older-0", "newer-0"}  # 1h and 2h are closest
    # newer-1 (10h) and older-1 (5h) compete for spot 3; older-1 wins
    assert "older-1" in contents
    # Furthest (30h, 20h) excluded
    assert "newer-2" not in contents
    assert "older-2" not in contents


@pytest.mark.asyncio
async def test_expand_skips_superseded_neighbors(async_session) -> None:
    """Superseded items are excluded from the neighbor set."""
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    raw_session = await _create_raw(async_session, source="claude-code-session")
    target = await _create_memory_item(
        async_session, raw=raw_session, content="target", created_at=base
    )

    await _create_memory_item(
        async_session,
        source="claude-code-session",
        content="superseded-neighbor",
        is_superseded=True,
        created_at=base - timedelta(minutes=5),
    )
    await _create_memory_item(
        async_session,
        source="claude-code-session",
        content="live-neighbor",
        created_at=base + timedelta(hours=4),
    )
    await async_session.commit()

    result = await expand_memory(async_session, memory_id=str(target.id))

    contents = [n.content for n in result.neighbors]
    assert "superseded-neighbor" not in contents
    assert "live-neighbor" in contents


@pytest.mark.asyncio
async def test_expand_empty_neighbors_when_none(async_session) -> None:
    """Neighbors list is empty when no same-source siblings exist."""
    item = await _create_memory_item(async_session, source="claude-code-session")
    # Off-source row that must not become a neighbor.
    await _create_memory_item(async_session, source="api", content="other")
    await async_session.commit()

    result = await expand_memory(async_session, memory_id=str(item.id))

    assert result.neighbors == []


# ── HTTP route tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_expand_route_returns_payload(test_client, api_key_headers, async_session) -> None:
    """GET /v1/memory/{id}/expand returns full content + neighbors via HTTP."""
    base = datetime(2026, 5, 10, 9, 0, tzinfo=UTC)
    raw_session = await _create_raw(async_session, raw_text="raw text body")
    target = await _create_memory_item(
        async_session, raw=raw_session, content="main content", created_at=base
    )
    await _create_memory_item(
        async_session,
        source="claude-code-session",
        content="neighbor content",
        created_at=base + timedelta(hours=1),
    )
    await async_session.commit()

    resp = await test_client.get(f"/v1/memory/{target.id}/expand", headers=api_key_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["memory_id"] == str(target.id)
    assert body["content"] == "main content"
    assert body["raw_text"] == "raw text body"
    assert len(body["neighbors"]) == 1
    assert body["neighbors"][0]["content"] == "neighbor content"
    assert body["metadata"]["source"] == "claude-code-session"


@pytest.mark.asyncio
async def test_expand_route_invalid_uuid_returns_422(test_client, api_key_headers) -> None:
    """Non-UUID memory_id returns 422."""
    resp = await test_client.get("/v1/memory/not-a-uuid/expand", headers=api_key_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_expand_route_missing_returns_404(test_client, api_key_headers) -> None:
    """Unknown memory_id returns 404."""
    resp = await test_client.get(f"/v1/memory/{uuid4()}/expand", headers=api_key_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_expand_route_superseded_returns_404(
    test_client, api_key_headers, async_session
) -> None:
    """Superseded item returns 404 (caller should not chase outdated entries)."""
    item = await _create_memory_item(async_session, is_superseded=True)
    await async_session.commit()

    resp = await test_client.get(f"/v1/memory/{item.id}/expand", headers=api_key_headers)
    assert resp.status_code == 404
