"""Tests for GET /v1/memory/recent endpoint."""

from uuid import uuid4

import pytest

from src.core.models import MemoryItem, RawMemory


async def _create_raw(session):
    """Insert a minimal RawMemory row and return its UUID id."""
    raw = RawMemory(
        source="test",
        raw_text="test content",
        content_hash=uuid4().hex,
    )
    session.add(raw)
    await session.flush()
    return raw.id  # return UUID object, not str


async def _create_memory_item(
    session,
    *,
    content: str = "test memory",
    type_: str = "memory",
    is_superseded: bool = False,
) -> MemoryItem:
    """Insert a MemoryItem (with parent RawMemory) and return it."""
    raw_id = await _create_raw(session)
    item = MemoryItem(
        raw_id=raw_id,
        type=type_,
        content=content,
        summary=None,
        base_importance=0.5,
        dynamic_importance=0.0,
        is_superseded=is_superseded,
    )
    session.add(item)
    await session.flush()
    return item


# ── Basic listing ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_recent_empty(test_client, api_key_headers) -> None:
    """Returns empty list and total=0 when no memory items exist."""
    resp = await test_client.get("/v1/memory/recent", headers=api_key_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_memory_recent_returns_items(test_client, api_key_headers, async_session) -> None:
    """Returns non-superseded items with correct total count."""
    await _create_memory_item(async_session, content="first")
    await _create_memory_item(async_session, content="second")
    await async_session.commit()

    resp = await test_client.get("/v1/memory/recent", headers=api_key_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    contents = {item["content"] for item in body["items"]}
    assert contents == {"first", "second"}


# ── Superseded exclusion ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_recent_excludes_superseded(
    test_client, api_key_headers, async_session
) -> None:
    """Superseded items are excluded from results."""
    await _create_memory_item(async_session, content="active")
    await _create_memory_item(async_session, content="old", is_superseded=True)
    await async_session.commit()

    resp = await test_client.get("/v1/memory/recent", headers=api_key_headers)
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["content"] == "active"


# ── Type filter ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_recent_type_filter(test_client, api_key_headers, async_session) -> None:
    """type_filter narrows results to matching type."""
    await _create_memory_item(async_session, content="a memory", type_="memory")
    await _create_memory_item(async_session, content="a decision", type_="decision")
    await _create_memory_item(async_session, content="a task", type_="task")
    await async_session.commit()

    resp = await test_client.get(
        "/v1/memory/recent?type_filter=decision", headers=api_key_headers
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["type"] == "decision"
    assert body["items"][0]["content"] == "a decision"


@pytest.mark.asyncio
async def test_memory_recent_type_filter_no_match(
    test_client, api_key_headers, async_session
) -> None:
    """type_filter with no matching items returns empty list."""
    await _create_memory_item(async_session, content="a memory", type_="memory")
    await async_session.commit()

    resp = await test_client.get(
        "/v1/memory/recent?type_filter=decision", headers=api_key_headers
    )
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


# ── Pagination ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_recent_pagination(test_client, api_key_headers, async_session) -> None:
    """limit and offset control pagination; total reflects full count."""
    for i in range(5):
        await _create_memory_item(async_session, content=f"item-{i}")
    await async_session.commit()

    resp = await test_client.get("/v1/memory/recent?limit=2&offset=0", headers=api_key_headers)
    body = resp.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2

    resp2 = await test_client.get("/v1/memory/recent?limit=2&offset=2", headers=api_key_headers)
    body2 = resp2.json()
    assert body2["total"] == 5
    assert len(body2["items"]) == 2
    # No overlap between pages
    ids_page1 = {item["id"] for item in body["items"]}
    ids_page2 = {item["id"] for item in body2["items"]}
    assert ids_page1.isdisjoint(ids_page2)


# ── Response shape ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_recent_response_fields(
    test_client, api_key_headers, async_session
) -> None:
    """Each item in response has the full MemoryItemResponse fields."""
    await _create_memory_item(async_session, content="detailed item", type_="decision")
    await async_session.commit()

    resp = await test_client.get("/v1/memory/recent", headers=api_key_headers)
    item = resp.json()["items"][0]
    assert "id" in item
    assert "raw_id" in item
    assert item["type"] == "decision"
    assert item["content"] == "detailed item"
    assert "base_importance" in item
    assert "dynamic_importance" in item
    assert "is_superseded" in item
    assert "created_at" in item


# ── Auth ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_recent_requires_auth(test_client) -> None:
    """Request without API key returns 401."""
    resp = await test_client.get("/v1/memory/recent")
    assert resp.status_code == 401
