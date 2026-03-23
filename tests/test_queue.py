"""Tests for CP 2.7: dead-letter queue endpoints.

Covers:
  GET  /v1/dead-letters
  POST /v1/dead-letters/{failed_id}/retry
"""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.core.models import FailedRefinement, RawMemory, RefinementQueue


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


async def _make_dead_letter(
    async_session, retry_count: int = 0, resolved: bool = False
) -> FailedRefinement:
    """Helper to create a full RawMemory → RefinementQueue → FailedRefinement chain."""
    raw = RawMemory(source="test", raw_text="failing text")
    async_session.add(raw)
    await async_session.flush()

    queue_row = RefinementQueue(raw_id=raw.id, status="failed", attempts=3)
    async_session.add(queue_row)
    await async_session.flush()

    failed = FailedRefinement(
        raw_id=raw.id,
        queue_id=queue_row.id,
        error_reason="extraction failed",
        attempt_count=3,
        retry_count=retry_count,
        resolved_at=datetime.now(timezone.utc) if resolved else None,
    )
    async_session.add(failed)
    await async_session.flush()
    await async_session.commit()
    return failed


@pytest_asyncio.fixture
async def dead_letter(async_session) -> FailedRefinement:
    """Unresolved dead-letter with retry_count=0."""
    return await _make_dead_letter(async_session, retry_count=0)


@pytest_asyncio.fixture
async def dead_letter_at_limit(async_session) -> FailedRefinement:
    """Unresolved dead-letter at retry limit (retry_count=3)."""
    return await _make_dead_letter(async_session, retry_count=3)


@pytest_asyncio.fixture
async def resolved_dead_letter(async_session) -> FailedRefinement:
    """Resolved dead-letter."""
    return await _make_dead_letter(async_session, retry_count=1, resolved=True)


# ── GET /v1/dead-letters ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_dead_letters_empty_returns_empty_list(client, auth_headers):
    resp = await client.get("/v1/dead-letters", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_list_dead_letters_returns_unresolved_by_default(client, auth_headers, dead_letter):
    resp = await client.get("/v1/dead-letters", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    ids = [i["id"] for i in body["items"]]
    assert str(dead_letter.id) in ids


@pytest.mark.asyncio
async def test_list_dead_letters_resolved_false_returns_unresolved(client, auth_headers, dead_letter):
    resp = await client.get("/v1/dead-letters?resolved=false", headers=auth_headers)
    assert resp.status_code == 200
    ids = [i["id"] for i in resp.json()["items"]]
    assert str(dead_letter.id) in ids


@pytest.mark.asyncio
async def test_list_dead_letters_resolved_true_returns_resolved(
    client, auth_headers, dead_letter, resolved_dead_letter
):
    resp = await client.get("/v1/dead-letters?resolved=true", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    ids = [i["id"] for i in body["items"]]
    assert str(resolved_dead_letter.id) in ids
    assert str(dead_letter.id) not in ids


@pytest.mark.asyncio
async def test_list_dead_letters_default_hides_resolved(
    client, auth_headers, dead_letter, resolved_dead_letter
):
    resp = await client.get("/v1/dead-letters", headers=auth_headers)
    assert resp.status_code == 200
    ids = [i["id"] for i in resp.json()["items"]]
    assert str(dead_letter.id) in ids
    assert str(resolved_dead_letter.id) not in ids


@pytest.mark.asyncio
async def test_list_dead_letters_response_shape(client, auth_headers, dead_letter):
    resp = await client.get("/v1/dead-letters", headers=auth_headers)
    item = resp.json()["items"][0]
    assert "id" in item
    assert "raw_id" in item
    assert "queue_id" in item
    assert "error_reason" in item
    assert "attempt_count" in item
    assert "last_output" in item
    assert "retry_count" in item
    assert "created_at" in item
    assert "resolved_at" in item


@pytest.mark.asyncio
async def test_list_dead_letters_limit_and_offset(client, auth_headers, async_session):
    for _ in range(4):
        await _make_dead_letter(async_session)

    resp = await client.get("/v1/dead-letters?limit=2&offset=1", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["total"] == 4


@pytest.mark.asyncio
async def test_list_dead_letters_requires_auth(client):
    resp = await client.get("/v1/dead-letters")
    assert resp.status_code == 401


# ── POST /v1/dead-letters/{failed_id}/retry ───────────────────────────────────


@pytest.mark.asyncio
async def test_retry_dead_letter_returns_200(client, auth_headers, dead_letter):
    resp = await client.post(f"/v1/dead-letters/{dead_letter.id}/retry", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["retry_count"] == 1
    assert body["id"] == str(dead_letter.id)
    assert "queue_id" in body
    assert body["message"] == "Re-enqueued for processing"


@pytest.mark.asyncio
async def test_retry_dead_letter_increments_retry_count(
    client, auth_headers, dead_letter, async_session
):
    await client.post(f"/v1/dead-letters/{dead_letter.id}/retry", headers=auth_headers)

    await async_session.refresh(dead_letter)
    assert dead_letter.retry_count == 1


@pytest.mark.asyncio
async def test_retry_dead_letter_resets_queue_to_pending(
    client, auth_headers, dead_letter, async_session
):
    await client.post(f"/v1/dead-letters/{dead_letter.id}/retry", headers=auth_headers)

    result = await async_session.execute(
        select(RefinementQueue).where(RefinementQueue.id == dead_letter.queue_id)
    )
    queue_row = result.scalar_one()
    assert queue_row.status == "pending"
    assert queue_row.attempts == 0
    assert queue_row.locked_at is None


@pytest.mark.asyncio
async def test_retry_dead_letter_not_found_returns_404(client, auth_headers):
    resp = await client.post(f"/v1/dead-letters/{uuid.uuid4()}/retry", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_retry_dead_letter_invalid_uuid_returns_422(client, auth_headers):
    resp = await client.post("/v1/dead-letters/not-a-uuid/retry", headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_retry_dead_letter_at_limit_returns_409(client, auth_headers, dead_letter_at_limit):
    resp = await client.post(
        f"/v1/dead-letters/{dead_letter_at_limit.id}/retry", headers=auth_headers
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_retry_dead_letter_exactly_at_limit_returns_409(client, auth_headers, async_session):
    failed = await _make_dead_letter(async_session, retry_count=3)
    resp = await client.post(f"/v1/dead-letters/{failed.id}/retry", headers=auth_headers)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_retry_dead_letter_one_below_limit_succeeds(client, auth_headers, async_session):
    # retry_count=2, limit=3 → this is the 3rd retry (allowed); 4th would be refused
    failed = await _make_dead_letter(async_session, retry_count=2)
    resp = await client.post(f"/v1/dead-letters/{failed.id}/retry", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["retry_count"] == 3


@pytest.mark.asyncio
async def test_retry_dead_letter_requires_auth(client, dead_letter):
    resp = await client.post(f"/v1/dead-letters/{dead_letter.id}/retry")
    assert resp.status_code == 401


# ── GET /v1/queue/status ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_queue_status_empty_db(client, auth_headers):
    """GET /v1/queue/status on empty DB returns all-zero counts."""
    resp = await client.get("/v1/queue/status", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["pending"] == 0
    assert body["processing"] == 0
    assert body["done"] == 0
    assert body["failed"] == 0
    assert body["total"] == 0
    assert body["oldest_locked_at"] is None


@pytest.mark.asyncio
async def test_queue_status_counts_by_status(client, auth_headers, async_session):
    """GET /v1/queue/status returns correct per-status counts."""
    raw = RawMemory(source="test", raw_text="test")
    async_session.add(raw)
    await async_session.flush()

    pending_row = RefinementQueue(raw_id=raw.id, status="pending")
    async_session.add(pending_row)

    raw2 = RawMemory(source="test", raw_text="test2")
    async_session.add(raw2)
    await async_session.flush()
    done_row = RefinementQueue(raw_id=raw2.id, status="done")
    async_session.add(done_row)

    await async_session.commit()

    resp = await client.get("/v1/queue/status", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["pending"] == 1
    assert body["done"] == 1
    assert body["total"] == 2


@pytest.mark.asyncio
async def test_queue_status_response_shape(client, auth_headers):
    """GET /v1/queue/status response contains all expected fields."""
    resp = await client.get("/v1/queue/status", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "pending" in body
    assert "processing" in body
    assert "done" in body
    assert "failed" in body
    assert "total" in body
    assert "oldest_locked_at" in body


@pytest.mark.asyncio
async def test_queue_status_requires_auth(client):
    """GET /v1/queue/status without X-API-Key returns 401."""
    resp = await client.get("/v1/queue/status")
    assert resp.status_code == 401


# ── Security: synthesis error message (H2) ───────────────────────────────────


@pytest.mark.asyncio
async def test_synthesis_500_returns_generic_message(client, auth_headers, monkeypatch):
    """POST /v1/synthesis/run when LLM raises returns 500 with generic message (H2).

    The response body must NOT contain raw exception details, tracebacks,
    or Anthropic API error strings.
    """
    from unittest.mock import AsyncMock, patch

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    with patch("src.jobs.synthesis.run_synthesis_job", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError(
            "Anthropic API error: 500 Internal Server Error — connection refused"
        )

        resp = await client.post("/v1/synthesis/run", json={"days": 7}, headers=auth_headers)

    assert resp.status_code == 500
    body = resp.json()
    detail = body["detail"]
    # Must be generic — no raw exception content
    assert "Anthropic" not in detail
    assert "connection refused" not in detail
    assert "traceback" not in detail.lower()
    assert "internal error" in detail.lower() or "server logs" in detail.lower()
