"""Tests for GET /v1/jobs/history endpoint.

Covers pagination, filtering by job_name and status, ordering, and auth.
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.core.models import JobRun

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


async def _make_job_run(
    async_session,
    job_name: str = "pulse",
    status: str = "success",
    started_at: datetime | None = None,
    error_message: str | None = None,
    duration_seconds: float = 1.5,
) -> JobRun:
    """Helper to create a JobRun row."""
    now = datetime.now(UTC)
    started = started_at or now
    run = JobRun(
        job_name=job_name,
        started_at=started,
        finished_at=started + timedelta(seconds=duration_seconds),
        status=status,
        error_message=error_message,
        duration_seconds=duration_seconds,
    )
    async_session.add(run)
    await async_session.flush()
    await async_session.commit()
    return run


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_job_history_empty_db(client, auth_headers):
    resp = await client.get("/v1/jobs/history", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_job_history_returns_all_runs(client, auth_headers, async_session):
    await _make_job_run(async_session, job_name="pulse")
    await _make_job_run(async_session, job_name="synthesis")
    await _make_job_run(async_session, job_name="importance")

    resp = await client.get("/v1/jobs/history", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3


@pytest.mark.asyncio
async def test_job_history_filter_by_job_name(client, auth_headers, async_session):
    await _make_job_run(async_session, job_name="pulse")
    await _make_job_run(async_session, job_name="synthesis")

    resp = await client.get("/v1/jobs/history?job_name=pulse", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["job_name"] == "pulse"


@pytest.mark.asyncio
async def test_job_history_filter_by_status(client, auth_headers, async_session):
    await _make_job_run(async_session, status="success")
    await _make_job_run(async_session, status="failed", error_message="boom")

    resp = await client.get("/v1/jobs/history?status=failed", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_job_history_combined_filters(client, auth_headers, async_session):
    await _make_job_run(async_session, job_name="pulse", status="success")
    await _make_job_run(async_session, job_name="pulse", status="failed", error_message="err")
    await _make_job_run(async_session, job_name="synthesis", status="failed", error_message="err")

    resp = await client.get(
        "/v1/jobs/history?job_name=pulse&status=failed", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["job_name"] == "pulse"
    assert body["items"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_job_history_pagination(client, auth_headers, async_session):
    for i in range(5):
        await _make_job_run(
            async_session,
            started_at=datetime(2026, 1, 1 + i, tzinfo=UTC),
        )

    resp = await client.get("/v1/jobs/history?limit=2&offset=1", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["total"] == 5


@pytest.mark.asyncio
async def test_job_history_ordered_by_started_at_desc(client, auth_headers, async_session):
    early = await _make_job_run(
        async_session,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    late = await _make_job_run(
        async_session,
        started_at=datetime(2026, 6, 1, tzinfo=UTC),
    )

    resp = await client.get("/v1/jobs/history", headers=auth_headers)
    body = resp.json()
    assert body["items"][0]["id"] == str(late.id)
    assert body["items"][1]["id"] == str(early.id)


@pytest.mark.asyncio
async def test_job_history_response_shape(client, auth_headers, async_session):
    await _make_job_run(async_session, error_message="test error")

    resp = await client.get("/v1/jobs/history", headers=auth_headers)
    item = resp.json()["items"][0]
    assert "id" in item
    assert "job_name" in item
    assert "started_at" in item
    assert "finished_at" in item
    assert "status" in item
    assert "error_message" in item
    assert "duration_seconds" in item
    assert "created_at" in item


@pytest.mark.asyncio
async def test_job_history_requires_auth(client):
    resp = await client.get("/v1/jobs/history")
    assert resp.status_code == 401
