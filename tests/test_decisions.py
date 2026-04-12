"""Tests for CP 2.6: decision endpoints.

Covers:
  GET  /v1/decisions
  POST /v1/decisions
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.core.models import Decision, MemoryItem, RawMemory

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
    return {"X-API-Key": "test-secret-key"}


@pytest_asyncio.fixture
async def memory_item(async_session) -> MemoryItem:
    """A committed RawMemory + MemoryItem pair."""
    raw = RawMemory(source="test", raw_text="test text")
    async_session.add(raw)
    await async_session.flush()

    item = MemoryItem(
        raw_id=raw.id,
        type="context",
        content="test content",
        summary="test summary",
        base_importance=0.5,
    )
    async_session.add(item)
    await async_session.flush()
    await async_session.commit()
    return item


@pytest_asyncio.fixture
async def memory_item_b(async_session) -> MemoryItem:
    """A second committed MemoryItem for filter tests."""
    raw = RawMemory(source="test", raw_text="other text")
    async_session.add(raw)
    await async_session.flush()

    item = MemoryItem(
        raw_id=raw.id,
        type="context",
        content="other content",
        summary="other summary",
        base_importance=0.3,
    )
    async_session.add(item)
    await async_session.flush()
    await async_session.commit()
    return item


@pytest_asyncio.fixture
async def decision(async_session, memory_item) -> Decision:
    d = Decision(
        memory_id=memory_item.id,
        decision="Use PostgreSQL",
        reasoning="Better for production",
        alternatives=["MySQL", "SQLite"],
    )
    async_session.add(d)
    await async_session.flush()
    await async_session.commit()
    return d


# ── GET /v1/decisions ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_decisions_empty_returns_empty_list(client, auth_headers):
    resp = await client.get("/v1/decisions", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["decisions"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_list_decisions_returns_200_with_decisions(client, auth_headers, decision):
    resp = await client.get("/v1/decisions", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    decisions = [d["decision"] for d in body["decisions"]]
    assert "Use PostgreSQL" in decisions


@pytest.mark.asyncio
async def test_list_decisions_response_shape(client, auth_headers, decision):
    resp = await client.get("/v1/decisions", headers=auth_headers)
    d = resp.json()["decisions"][0]
    assert "id" in d
    assert "memory_id" in d
    assert "decision" in d
    assert "reasoning" in d
    assert "alternatives" in d
    assert "created_at" in d


@pytest.mark.asyncio
async def test_list_decisions_filter_by_memory_id(
    client, auth_headers, async_session, memory_item, memory_item_b
):
    d1 = Decision(memory_id=memory_item.id, decision="Decision A", reasoning="Reason A")
    d2 = Decision(memory_id=memory_item_b.id, decision="Decision B", reasoning="Reason B")
    async_session.add(d1)
    async_session.add(d2)
    await async_session.flush()
    await async_session.commit()

    resp = await client.get(f"/v1/decisions?memory_id={memory_item.id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    decisions_text = [d["decision"] for d in body["decisions"]]
    assert "Decision A" in decisions_text
    assert "Decision B" not in decisions_text
    assert body["total"] == 1


@pytest.mark.asyncio
async def test_list_decisions_filter_by_invalid_memory_id_uuid_returns_422(client, auth_headers):
    resp = await client.get("/v1/decisions?memory_id=not-a-uuid", headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_decisions_limit_and_offset(client, auth_headers, async_session, memory_item):
    for i in range(5):
        d = Decision(memory_id=memory_item.id, decision=f"Decision {i}", reasoning="reason")
        async_session.add(d)
    await async_session.flush()
    await async_session.commit()

    resp = await client.get("/v1/decisions?limit=2&offset=1", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["decisions"]) == 2
    assert body["total"] == 5


@pytest.mark.asyncio
async def test_list_decisions_total_matches_filter(
    client, auth_headers, async_session, memory_item, memory_item_b
):
    async_session.add(Decision(memory_id=memory_item.id, decision="D1", reasoning="R1"))
    async_session.add(Decision(memory_id=memory_item.id, decision="D2", reasoning="R2"))
    async_session.add(Decision(memory_id=memory_item_b.id, decision="D3", reasoning="R3"))
    await async_session.flush()
    await async_session.commit()

    resp = await client.get(f"/v1/decisions?memory_id={memory_item.id}", headers=auth_headers)
    body = resp.json()
    assert body["total"] == 2
    assert len(body["decisions"]) == 2


@pytest.mark.asyncio
async def test_list_decisions_requires_auth(client):
    resp = await client.get("/v1/decisions")
    assert resp.status_code == 401


# ── POST /v1/decisions ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_decision_returns_201(client, auth_headers, memory_item):
    payload = {
        "memory_id": str(memory_item.id),
        "decision": "Use async everywhere",
        "reasoning": "Performance",
    }
    resp = await client.post("/v1/decisions", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["decision"] == "Use async everywhere"
    assert body["reasoning"] == "Performance"
    assert body["memory_id"] == str(memory_item.id)
    assert "id" in body
    assert "created_at" in body


@pytest.mark.asyncio
async def test_create_decision_persists_in_db(client, auth_headers, memory_item, async_session):
    payload = {
        "memory_id": str(memory_item.id),
        "decision": "Persisted decision",
        "reasoning": "Testing persistence",
    }
    await client.post("/v1/decisions", json=payload, headers=auth_headers)

    result = await async_session.execute(
        select(Decision).where(Decision.decision == "Persisted decision")
    )
    d = result.scalar_one_or_none()
    assert d is not None
    assert d.reasoning == "Testing persistence"


@pytest.mark.asyncio
async def test_create_decision_with_alternatives(client, auth_headers, memory_item):
    payload = {
        "memory_id": str(memory_item.id),
        "decision": "Use Redis",
        "reasoning": "Speed",
        "alternatives": ["Memcached", "Local cache"],
    }
    resp = await client.post("/v1/decisions", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["alternatives"] == ["Memcached", "Local cache"]


@pytest.mark.asyncio
async def test_create_decision_alternatives_none_by_default(client, auth_headers, memory_item):
    payload = {
        "memory_id": str(memory_item.id),
        "decision": "No alternatives",
        "reasoning": "Only option",
    }
    resp = await client.post("/v1/decisions", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["alternatives"] is None


@pytest.mark.asyncio
async def test_create_decision_memory_id_not_found_returns_404(client, auth_headers):
    payload = {
        "memory_id": str(uuid.uuid4()),
        "decision": "Orphan decision",
        "reasoning": "No parent",
    }
    resp = await client.post("/v1/decisions", json=payload, headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_decision_invalid_memory_id_uuid_returns_422(client, auth_headers):
    payload = {"memory_id": "not-a-uuid", "decision": "Bad decision", "reasoning": "reason"}
    resp = await client.post("/v1/decisions", json=payload, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_decision_missing_decision_returns_422(client, auth_headers, memory_item):
    payload = {"memory_id": str(memory_item.id), "reasoning": "no decision field"}
    resp = await client.post("/v1/decisions", json=payload, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_decision_missing_reasoning_returns_422(client, auth_headers, memory_item):
    payload = {"memory_id": str(memory_item.id), "decision": "no reasoning field"}
    resp = await client.post("/v1/decisions", json=payload, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_decision_requires_auth(client, memory_item):
    payload = {
        "memory_id": str(memory_item.id),
        "decision": "Unauth decision",
        "reasoning": "reason",
    }
    resp = await client.post("/v1/decisions", json=payload)
    assert resp.status_code == 401
