"""Tests for CP 2.6: task endpoints.

Covers:
  GET   /v1/tasks
  POST  /v1/tasks
  PATCH /v1/tasks/{task_id}
"""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.core.models import MemoryItem, RawMemory, Task


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
    """A committed RawMemory + MemoryItem pair for use as a FK target."""
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
async def open_task(async_session, memory_item) -> Task:
    task = Task(memory_id=memory_item.id, description="Open task", owner="alice", status="open")
    async_session.add(task)
    await async_session.flush()
    await async_session.commit()
    return task


@pytest_asyncio.fixture
async def done_task(async_session, memory_item) -> Task:
    task = Task(memory_id=memory_item.id, description="Done task", owner="bob", status="done")
    async_session.add(task)
    await async_session.flush()
    await async_session.commit()
    return task


# ── GET /v1/tasks ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_tasks_empty_returns_empty_list(client, auth_headers):
    resp = await client.get("/v1/tasks", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["tasks"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_list_tasks_returns_200_with_tasks(client, auth_headers, open_task):
    resp = await client.get("/v1/tasks", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    descriptions = [t["description"] for t in body["tasks"]]
    assert "Open task" in descriptions


@pytest.mark.asyncio
async def test_list_tasks_response_shape(client, auth_headers, open_task):
    resp = await client.get("/v1/tasks", headers=auth_headers)
    task = resp.json()["tasks"][0]
    assert "id" in task
    assert "memory_id" in task
    assert "description" in task
    assert "owner" in task
    assert "due_date" in task
    assert "status" in task
    assert "created_at" in task


@pytest.mark.asyncio
async def test_list_tasks_filter_by_status_open(client, auth_headers, open_task, done_task):
    resp = await client.get("/v1/tasks?status=open", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert all(t["status"] == "open" for t in body["tasks"])
    descriptions = [t["description"] for t in body["tasks"]]
    assert "Open task" in descriptions
    assert "Done task" not in descriptions


@pytest.mark.asyncio
async def test_list_tasks_filter_by_status_done(client, auth_headers, open_task, done_task):
    resp = await client.get("/v1/tasks?status=done", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert all(t["status"] == "done" for t in body["tasks"])
    descriptions = [t["description"] for t in body["tasks"]]
    assert "Done task" in descriptions
    assert "Open task" not in descriptions


@pytest.mark.asyncio
async def test_list_tasks_filter_by_owner(client, auth_headers, open_task, done_task):
    resp = await client.get("/v1/tasks?owner=alice", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert all(t["owner"] == "alice" for t in body["tasks"])
    descriptions = [t["description"] for t in body["tasks"]]
    assert "Open task" in descriptions
    assert "Done task" not in descriptions


@pytest.mark.asyncio
async def test_list_tasks_filter_by_due_before(client, auth_headers, async_session, memory_item):
    past = Task(
        memory_id=memory_item.id,
        description="Past task",
        due_date=datetime(2020, 1, 1, tzinfo=timezone.utc),
        status="open",
    )
    future = Task(
        memory_id=memory_item.id,
        description="Future task",
        due_date=datetime(2099, 1, 1, tzinfo=timezone.utc),
        status="open",
    )
    async_session.add(past)
    async_session.add(future)
    await async_session.flush()
    await async_session.commit()

    resp = await client.get("/v1/tasks?due_before=2030-01-01T00:00:00", headers=auth_headers)
    assert resp.status_code == 200
    descriptions = [t["description"] for t in resp.json()["tasks"]]
    assert "Past task" in descriptions
    assert "Future task" not in descriptions


@pytest.mark.asyncio
async def test_list_tasks_limit_and_offset(client, auth_headers, async_session, memory_item):
    for i in range(5):
        t = Task(memory_id=memory_item.id, description=f"Task {i}", status="open")
        async_session.add(t)
    await async_session.flush()
    await async_session.commit()

    resp = await client.get("/v1/tasks?limit=2&offset=1", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["tasks"]) == 2
    assert body["total"] == 5


@pytest.mark.asyncio
async def test_list_tasks_total_reflects_filter(client, auth_headers, open_task, done_task):
    resp = await client.get("/v1/tasks?status=open", headers=auth_headers)
    body = resp.json()
    assert body["total"] == 1
    assert len(body["tasks"]) == 1


@pytest.mark.asyncio
async def test_list_tasks_requires_auth(client):
    resp = await client.get("/v1/tasks")
    assert resp.status_code == 401


# ── POST /v1/tasks ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_task_returns_201(client, auth_headers, memory_item):
    payload = {"memory_id": str(memory_item.id), "description": "Write tests"}
    resp = await client.post("/v1/tasks", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["description"] == "Write tests"
    assert body["status"] == "open"
    assert body["memory_id"] == str(memory_item.id)
    assert "id" in body
    assert "created_at" in body


@pytest.mark.asyncio
async def test_create_task_persists_in_db(client, auth_headers, memory_item, async_session):
    payload = {"memory_id": str(memory_item.id), "description": "Persisted task"}
    await client.post("/v1/tasks", json=payload, headers=auth_headers)

    result = await async_session.execute(select(Task).where(Task.description == "Persisted task"))
    task = result.scalar_one_or_none()
    assert task is not None
    assert task.status == "open"


@pytest.mark.asyncio
async def test_create_task_with_optional_fields(client, auth_headers, memory_item):
    payload = {
        "memory_id": str(memory_item.id),
        "description": "Task with extras",
        "owner": "alice",
        "due_date": "2030-06-01T00:00:00",
        "status": "done",
    }
    resp = await client.post("/v1/tasks", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["owner"] == "alice"
    assert body["status"] == "done"
    assert body["due_date"] is not None


@pytest.mark.asyncio
async def test_create_task_memory_id_not_found_returns_404(client, auth_headers):
    payload = {"memory_id": str(uuid.uuid4()), "description": "Orphan task"}
    resp = await client.post("/v1/tasks", json=payload, headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_task_invalid_memory_id_uuid_returns_422(client, auth_headers):
    payload = {"memory_id": "not-a-uuid", "description": "Bad task"}
    resp = await client.post("/v1/tasks", json=payload, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_task_invalid_status_returns_422(client, auth_headers, memory_item):
    payload = {"memory_id": str(memory_item.id), "description": "Bad status task", "status": "invalid"}
    resp = await client.post("/v1/tasks", json=payload, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_task_missing_description_returns_422(client, auth_headers, memory_item):
    payload = {"memory_id": str(memory_item.id)}
    resp = await client.post("/v1/tasks", json=payload, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_task_missing_memory_id_returns_422(client, auth_headers):
    payload = {"description": "No memory_id"}
    resp = await client.post("/v1/tasks", json=payload, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_task_requires_auth(client, memory_item):
    payload = {"memory_id": str(memory_item.id), "description": "Unauth task"}
    resp = await client.post("/v1/tasks", json=payload)
    assert resp.status_code == 401


# ── PATCH /v1/tasks/{task_id} ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_task_status_open_to_done(client, auth_headers, open_task):
    resp = await client.patch(
        f"/v1/tasks/{open_task.id}", json={"status": "done"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"


@pytest.mark.asyncio
async def test_update_task_status_persists_in_db(client, auth_headers, open_task, async_session):
    await client.patch(f"/v1/tasks/{open_task.id}", json={"status": "done"}, headers=auth_headers)

    await async_session.refresh(open_task)
    assert open_task.status == "done"


@pytest.mark.asyncio
async def test_update_task_status_to_cancelled(client, auth_headers, open_task):
    resp = await client.patch(
        f"/v1/tasks/{open_task.id}", json={"status": "cancelled"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_update_task_not_found_returns_404(client, auth_headers):
    resp = await client.patch(
        f"/v1/tasks/{uuid.uuid4()}", json={"status": "done"}, headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_task_invalid_uuid_returns_422(client, auth_headers):
    resp = await client.patch("/v1/tasks/not-a-uuid", json={"status": "done"}, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_task_invalid_status_value_returns_422(client, auth_headers, open_task):
    resp = await client.patch(
        f"/v1/tasks/{open_task.id}", json={"status": "bogus"}, headers=auth_headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_task_requires_auth(client, open_task):
    resp = await client.patch(f"/v1/tasks/{open_task.id}", json={"status": "done"})
    assert resp.status_code == 401
