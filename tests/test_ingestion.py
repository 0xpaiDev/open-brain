"""Tests for CP7: API ingestion endpoint, auth middleware, and health checks.

Covers: POST /v1/memory, GET /health, GET /ready
Auth: X-API-Key header validation
DB side effects: raw_memory + refinement_queue rows created
"""

import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy import func

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.core.models import MemoryItem, RawMemory, RefinementQueue
from src.api.routes.memory import _content_hash


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client(async_session, monkeypatch):
    """Test client with DB overridden to use in-memory SQLite session."""
    monkeypatch.setenv("SQLALCHEMY_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("API_KEY", "test-secret-key")

    from src.api.main import app
    from src.core.database import get_db

    async def override_get_db():
        yield async_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers() -> dict:
    """Valid X-API-Key headers for authenticated requests."""
    return {"X-API-Key": "test-secret-key"}


# ── POST /v1/memory ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_memory_returns_202(client, auth_headers):
    """POST /v1/memory with valid payload and auth returns 202 with raw_id."""
    resp = await client.post("/v1/memory", json={"text": "hello world"}, headers=auth_headers)
    assert resp.status_code == 202
    body = resp.json()
    assert "raw_id" in body
    assert body["status"] == "queued"
    # raw_id should be a valid UUID string
    import uuid
    uuid.UUID(body["raw_id"])  # raises if not valid UUID


@pytest.mark.asyncio
async def test_post_memory_creates_raw_memory_row(client, auth_headers, async_session):
    """POST /v1/memory inserts a row into raw_memory table."""
    resp = await client.post(
        "/v1/memory",
        json={"text": "store this memory", "source": "api"},
        headers=auth_headers,
    )
    assert resp.status_code == 202
    raw_id = resp.json()["raw_id"]

    result = await async_session.execute(select(RawMemory).where(RawMemory.id == uuid.UUID(raw_id)))
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.raw_text == "store this memory"
    assert row.source == "api"


@pytest.mark.asyncio
async def test_post_memory_creates_refinement_queue_row(client, auth_headers, async_session):
    """POST /v1/memory inserts a pending row into refinement_queue."""
    resp = await client.post("/v1/memory", json={"text": "queue me"}, headers=auth_headers)
    assert resp.status_code == 202
    raw_id = resp.json()["raw_id"]

    result = await async_session.execute(
        select(RefinementQueue).where(RefinementQueue.raw_id == uuid.UUID(raw_id))
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.status == "pending"
    assert row.attempts == 0


@pytest.mark.asyncio
async def test_post_memory_accepts_optional_fields(client, auth_headers, async_session):
    """POST /v1/memory accepts source and metadata optional fields."""
    resp = await client.post(
        "/v1/memory",
        json={"text": "with metadata", "source": "slack", "metadata": {"channel": "general"}},
        headers=auth_headers,
    )
    assert resp.status_code == 202
    raw_id = resp.json()["raw_id"]

    result = await async_session.execute(select(RawMemory).where(RawMemory.id == uuid.UUID(raw_id)))
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.source == "slack"
    assert row.metadata_ == {"channel": "general"}


# ── Auth tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_memory_no_auth_returns_401(client):
    """POST /v1/memory without X-API-Key header returns 401."""
    resp = await client.post("/v1/memory", json={"text": "no auth"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_post_memory_wrong_key_returns_401(client):
    """POST /v1/memory with wrong X-API-Key returns 401."""
    resp = await client.post(
        "/v1/memory",
        json={"text": "wrong key"},
        headers={"X-API-Key": "wrong-key"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_post_memory_bad_json_returns_422(client, auth_headers):
    """POST /v1/memory without required 'text' field returns 422."""
    resp = await client.post("/v1/memory", json={"wrong_field": "value"}, headers=auth_headers)
    assert resp.status_code == 422


# ── Health endpoints ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_endpoint_returns_200(client):
    """GET /health returns 200 with no auth required."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_ready_endpoint_checks_database(client):
    """GET /ready returns 200 when DB is accessible (no auth required).

    health_check() uses the global async_engine which is None in tests
    (init_db() is never called). We patch it to return True to simulate
    a healthy DB, since the route logic under test is the HTTP response shape.
    """
    with patch("src.api.routes.health.health_check", new_callable=AsyncMock, return_value=True):
        resp = await client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── Content-hash dedup ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_memory_duplicate_within_24h_returns_existing_id(client, auth_headers, async_session):
    """Submitting the same text twice within 24h returns the original raw_id with status='duplicate'."""
    resp1 = await client.post("/v1/memory", json={"text": "duplicate content"}, headers=auth_headers)
    assert resp1.status_code == 202
    original_raw_id = resp1.json()["raw_id"]
    assert resp1.json()["status"] == "queued"

    resp2 = await client.post("/v1/memory", json={"text": "duplicate content"}, headers=auth_headers)
    assert resp2.status_code == 202
    assert resp2.json()["raw_id"] == original_raw_id
    assert resp2.json()["status"] == "duplicate"


@pytest.mark.asyncio
async def test_post_memory_duplicate_normalizes_whitespace_and_case(client, auth_headers):
    """Whitespace variation and case differences are treated as the same content."""
    resp1 = await client.post("/v1/memory", json={"text": "Hello World"}, headers=auth_headers)
    assert resp1.status_code == 202
    original_raw_id = resp1.json()["raw_id"]

    resp2 = await client.post("/v1/memory", json={"text": "  hello  world  "}, headers=auth_headers)
    assert resp2.status_code == 202
    assert resp2.json()["raw_id"] == original_raw_id
    assert resp2.json()["status"] == "duplicate"


@pytest.mark.asyncio
async def test_post_memory_different_text_not_a_duplicate(client, auth_headers):
    """Different text content creates a distinct raw_memory row."""
    resp1 = await client.post("/v1/memory", json={"text": "first memory"}, headers=auth_headers)
    assert resp1.status_code == 202

    resp2 = await client.post("/v1/memory", json={"text": "second memory"}, headers=auth_headers)
    assert resp2.status_code == 202
    assert resp2.json()["raw_id"] != resp1.json()["raw_id"]
    assert resp2.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_post_memory_duplicate_no_queue_row_created(client, auth_headers, async_session):
    """Duplicate submission does not create a new refinement_queue row."""
    resp1 = await client.post("/v1/memory", json={"text": "no extra queue"}, headers=auth_headers)
    assert resp1.status_code == 202
    original_raw_id = resp1.json()["raw_id"]

    # Count queue rows before duplicate
    result_before = await async_session.execute(select(func.count()).select_from(RefinementQueue))
    count_before = result_before.scalar()

    resp2 = await client.post("/v1/memory", json={"text": "no extra queue"}, headers=auth_headers)
    assert resp2.status_code == 202
    assert resp2.json()["status"] == "duplicate"

    # Count queue rows after duplicate — must be unchanged
    result_after = await async_session.execute(select(func.count()).select_from(RefinementQueue))
    count_after = result_after.scalar()
    assert count_after == count_before


# ── Superseding chain (Phase 2.3) ─────────────────────────────────────────────


async def _create_memory_item(session) -> MemoryItem:
    """Helper: create a RawMemory + MemoryItem and return the MemoryItem."""
    raw = RawMemory(source="api", raw_text="original memory")
    session.add(raw)
    await session.flush()
    item = MemoryItem(
        raw_id=raw.id,
        type="memory",
        content="original memory content",
        embedding=[0.0] * 1024,
    )
    session.add(item)
    await session.flush()
    await session.commit()
    return item


@pytest.mark.asyncio
async def test_post_memory_supersedes_returns_202(client, auth_headers, async_session):
    """POST /v1/memory with valid supersedes_id returns 202 with supersedes_id echoed."""
    item = await _create_memory_item(async_session)

    resp = await client.post(
        "/v1/memory",
        json={"text": "correction text", "supersedes_id": str(item.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert body["supersedes_id"] == str(item.id)


@pytest.mark.asyncio
async def test_post_memory_supersedes_sets_is_superseded_true(client, auth_headers, async_session):
    """Posting with supersedes_id marks the original MemoryItem as is_superseded=True."""
    item = await _create_memory_item(async_session)

    resp = await client.post(
        "/v1/memory",
        json={"text": "this replaces the original", "supersedes_id": str(item.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 202

    await async_session.refresh(item)
    assert item.is_superseded is True


@pytest.mark.asyncio
async def test_post_memory_supersedes_stores_metadata_key(client, auth_headers, async_session):
    """The supersedes_memory_id side-channel key is stored in raw_memory.metadata_."""
    item = await _create_memory_item(async_session)

    resp = await client.post(
        "/v1/memory",
        json={"text": "side-channel test", "supersedes_id": str(item.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 202
    raw_id = resp.json()["raw_id"]

    result = await async_session.execute(select(RawMemory).where(RawMemory.id == uuid.UUID(raw_id)))
    raw = result.scalar_one()
    assert raw.metadata_["supersedes_memory_id"] == str(item.id)


@pytest.mark.asyncio
async def test_post_memory_supersedes_preserves_caller_metadata(client, auth_headers, async_session):
    """When both metadata and supersedes_id are provided, both coexist in raw.metadata_."""
    item = await _create_memory_item(async_session)

    resp = await client.post(
        "/v1/memory",
        json={
            "text": "correction with metadata",
            "metadata": {"channel": "slack"},
            "supersedes_id": str(item.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 202
    raw_id = resp.json()["raw_id"]

    result = await async_session.execute(select(RawMemory).where(RawMemory.id == uuid.UUID(raw_id)))
    raw = result.scalar_one()
    assert raw.metadata_["channel"] == "slack"
    assert raw.metadata_["supersedes_memory_id"] == str(item.id)


@pytest.mark.asyncio
async def test_post_memory_supersedes_invalid_uuid_returns_422(client, auth_headers):
    """POST with a malformed supersedes_id string returns 422."""
    resp = await client.post(
        "/v1/memory",
        json={"text": "bad uuid", "supersedes_id": "not-a-uuid"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_memory_supersedes_nonexistent_id_returns_404(client, auth_headers):
    """POST with a well-formed but non-existent supersedes_id returns 404."""
    resp = await client.post(
        "/v1/memory",
        json={"text": "ghost supersede", "supersedes_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_post_memory_no_supersedes_id_field_is_none(client, auth_headers):
    """Normal POST without supersedes_id returns supersedes_id=None in response."""
    resp = await client.post("/v1/memory", json={"text": "normal memory"}, headers=auth_headers)
    assert resp.status_code == 202
    assert resp.json()["supersedes_id"] is None


# ── Worker unit tests: store_memory_item supersedes propagation ───────────────


@pytest.mark.asyncio
async def test_store_memory_item_sets_supersedes_id(async_session):
    """store_memory_item() sets supersedes_id from raw.metadata_ side-channel."""
    from src.pipeline.extractor import ExtractionResult
    from src.pipeline.worker import store_memory_item

    # Create an original MemoryItem that will be superseded
    original_raw = RawMemory(source="api", raw_text="original")
    async_session.add(original_raw)
    await async_session.flush()
    original_item = MemoryItem(raw_id=original_raw.id, type="memory", content="original", embedding=[0.0] * 1024)
    async_session.add(original_item)
    await async_session.flush()

    # Create new RawMemory with supersedes side-channel
    raw = RawMemory(
        source="api",
        raw_text="correction",
        metadata_={"supersedes_memory_id": str(original_item.id)},
    )
    async_session.add(raw)
    await async_session.flush()
    queue = RefinementQueue(raw_id=raw.id)
    async_session.add(queue)
    await async_session.flush()

    extraction = ExtractionResult(type="memory", content="correction content")
    embedding = [0.1] * 1024

    memory_item = await store_memory_item(async_session, raw, queue, extraction, embedding, [])

    assert memory_item.supersedes_id is not None
    assert str(memory_item.supersedes_id) == str(original_item.id)


# ── GET /v1/memory/{memory_id} ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_memory_item_returns_200(client, auth_headers, async_session):
    """GET /v1/memory/{id} for an existing MemoryItem returns 200 with all fields."""
    item = await _create_memory_item(async_session)

    resp = await client.get(f"/v1/memory/{item.id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(item.id)
    assert body["type"] == "memory"
    assert body["content"] == "original memory content"
    assert "base_importance" in body
    assert "dynamic_importance" in body
    assert "is_superseded" in body
    assert body["is_superseded"] is False
    assert body["supersedes_id"] is None


@pytest.mark.asyncio
async def test_get_memory_item_not_found_returns_404(client, auth_headers):
    """GET /v1/memory/{id} with valid UUID that does not exist returns 404."""
    import uuid

    resp = await client.get(f"/v1/memory/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_memory_item_invalid_uuid_returns_422(client, auth_headers):
    """GET /v1/memory/{id} with a non-UUID path param returns 422."""
    resp = await client.get("/v1/memory/not-a-uuid", headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_memory_item_requires_auth(client, async_session):
    """GET /v1/memory/{id} without X-API-Key returns 401."""
    item = await _create_memory_item(async_session)
    resp = await client.get(f"/v1/memory/{item.id}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_store_memory_item_no_supersedes_when_metadata_none(async_session):
    """store_memory_item() sets supersedes_id=None when raw.metadata_ is None."""
    from src.pipeline.extractor import ExtractionResult
    from src.pipeline.worker import store_memory_item

    raw = RawMemory(source="api", raw_text="no side-channel", metadata_=None)
    async_session.add(raw)
    await async_session.flush()
    queue = RefinementQueue(raw_id=raw.id)
    async_session.add(queue)
    await async_session.flush()

    extraction = ExtractionResult(type="memory", content="some content")
    memory_item = await store_memory_item(async_session, raw, queue, extraction, [0.1] * 1024, [])

    assert memory_item.supersedes_id is None
