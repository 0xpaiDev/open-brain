"""Tests for CP7: API ingestion endpoint, auth middleware, and health checks.

Covers: POST /v1/memory, GET /health, GET /ready
Auth: X-API-Key header validation
DB side effects: raw_memory + refinement_queue rows created
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.core.models import RawMemory, RefinementQueue


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
