"""Tests for the Todo API endpoints.

Covers CRUD happy paths, validation errors, filter queries, and the
history append-only invariant. All tests use in-memory SQLite via conftest.
"""

import uuid

import pytest

# ── POST /v1/todos ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_todo_success(test_client, api_key_headers, async_session) -> None:
    """POST /v1/todos with valid data returns 201 and a TodoResponse."""
    resp = await test_client.post(
        "/v1/todos",
        json={"description": "buy groceries"},
        headers=api_key_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["description"] == "buy groceries"
    assert body["priority"] == "normal"
    assert body["status"] == "open"
    assert "id" in body
    assert "created_at" in body
    assert "updated_at" in body


@pytest.mark.asyncio
async def test_create_todo_with_all_fields(test_client, api_key_headers) -> None:
    """POST with priority and due_date populates all fields."""
    resp = await test_client.post(
        "/v1/todos",
        json={"description": "urgent thing", "priority": "high", "due_date": "2026-12-31T00:00:00Z"},
        headers=api_key_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["priority"] == "high"
    assert "2026-12-31" in body["due_date"]


@pytest.mark.asyncio
async def test_create_todo_missing_description(test_client, api_key_headers) -> None:
    """POST without description returns 422."""
    resp = await test_client.post("/v1/todos", json={}, headers=api_key_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_todo_invalid_priority(test_client, api_key_headers) -> None:
    """POST with an invalid priority returns 422."""
    resp = await test_client.post(
        "/v1/todos",
        json={"description": "test", "priority": "urgent"},
        headers=api_key_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_todo_writes_history_row(test_client, api_key_headers, async_session) -> None:
    """Creating a todo writes a 'created' history entry automatically."""
    from sqlalchemy import select
    from src.core.models import TodoHistory

    resp = await test_client.post(
        "/v1/todos",
        json={"description": "history check"},
        headers=api_key_headers,
    )
    assert resp.status_code == 201
    todo_id = resp.json()["id"]

    result = await async_session.execute(
        select(TodoHistory).where(TodoHistory.todo_id == uuid.UUID(todo_id))
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].event_type == "created"
    assert rows[0].new_value is not None


# ── GET /v1/todos ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_todos_returns_all(test_client, api_key_headers) -> None:
    """GET /v1/todos returns all todos with total count."""
    for i in range(3):
        await test_client.post(
            "/v1/todos", json={"description": f"item {i}"}, headers=api_key_headers
        )
    resp = await test_client.get("/v1/todos", headers=api_key_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert len(body["todos"]) == 3


@pytest.mark.asyncio
async def test_list_todos_filter_status(test_client, api_key_headers) -> None:
    """GET ?status=open returns only open todos."""
    resp1 = await test_client.post(
        "/v1/todos", json={"description": "open todo"}, headers=api_key_headers
    )
    todo_id = resp1.json()["id"]
    # close one
    await test_client.patch(
        f"/v1/todos/{todo_id}", json={"status": "done"}, headers=api_key_headers
    )
    # add another open
    await test_client.post(
        "/v1/todos", json={"description": "still open"}, headers=api_key_headers
    )

    resp = await test_client.get("/v1/todos?status=open", headers=api_key_headers)
    body = resp.json()
    assert body["total"] == 1
    assert body["todos"][0]["status"] == "open"


@pytest.mark.asyncio
async def test_list_todos_filter_priority(test_client, api_key_headers) -> None:
    """GET ?priority=high returns only high-priority todos."""
    await test_client.post(
        "/v1/todos", json={"description": "high one", "priority": "high"}, headers=api_key_headers
    )
    await test_client.post(
        "/v1/todos", json={"description": "normal one"}, headers=api_key_headers
    )
    resp = await test_client.get("/v1/todos?priority=high", headers=api_key_headers)
    body = resp.json()
    assert body["total"] == 1
    assert body["todos"][0]["priority"] == "high"


@pytest.mark.asyncio
async def test_list_todos_empty_state(test_client, api_key_headers) -> None:
    """GET /v1/todos with no data returns total=0 and empty list."""
    resp = await test_client.get("/v1/todos", headers=api_key_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["todos"] == []


# ── GET /v1/todos/{id} ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_todo_success(test_client, api_key_headers) -> None:
    """GET /v1/todos/{id} returns the correct todo."""
    created = (
        await test_client.post(
            "/v1/todos", json={"description": "findme"}, headers=api_key_headers
        )
    ).json()
    resp = await test_client.get(f"/v1/todos/{created['id']}", headers=api_key_headers)
    assert resp.status_code == 200
    assert resp.json()["description"] == "findme"


@pytest.mark.asyncio
async def test_get_todo_not_found(test_client, api_key_headers) -> None:
    """GET /v1/todos/{random-uuid} returns 404."""
    resp = await test_client.get(
        f"/v1/todos/{uuid.uuid4()}", headers=api_key_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_todo_invalid_uuid(test_client, api_key_headers) -> None:
    """GET /v1/todos/not-a-uuid returns 422."""
    resp = await test_client.get("/v1/todos/not-a-uuid", headers=api_key_headers)
    assert resp.status_code == 422


# ── PATCH /v1/todos/{id} ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_todo_done(test_client, api_key_headers, async_session) -> None:
    """PATCH status=done marks todo done and appends a 'completed' history row."""
    from sqlalchemy import select
    from src.core.models import TodoHistory

    created = (
        await test_client.post(
            "/v1/todos", json={"description": "finish me"}, headers=api_key_headers
        )
    ).json()
    todo_id = created["id"]

    resp = await test_client.patch(
        f"/v1/todos/{todo_id}", json={"status": "done"}, headers=api_key_headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"

    result = await async_session.execute(
        select(TodoHistory).where(TodoHistory.todo_id == uuid.UUID(todo_id))
    )
    rows = list(result.scalars().all())
    event_types = {r.event_type for r in rows}
    assert "completed" in event_types


@pytest.mark.asyncio
async def test_patch_todo_defer_with_reason(test_client, api_key_headers, async_session) -> None:
    """PATCH with due_date + reason appends a 'deferred' history row with reason."""
    from sqlalchemy import select
    from src.core.models import TodoHistory

    created = (
        await test_client.post(
            "/v1/todos", json={"description": "defer me"}, headers=api_key_headers
        )
    ).json()
    todo_id = created["id"]

    resp = await test_client.patch(
        f"/v1/todos/{todo_id}",
        json={"due_date": "2026-12-31T00:00:00Z", "reason": "busy this week"},
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    assert "2026-12-31" in resp.json()["due_date"]

    result = await async_session.execute(
        select(TodoHistory).where(TodoHistory.todo_id == uuid.UUID(todo_id))
    )
    rows = list(result.scalars().all())
    deferred = [r for r in rows if r.event_type == "deferred"]
    assert len(deferred) == 1
    assert deferred[0].reason == "busy this week"


@pytest.mark.asyncio
async def test_patch_todo_not_found(test_client, api_key_headers) -> None:
    """PATCH on a non-existent todo returns 404."""
    resp = await test_client.patch(
        f"/v1/todos/{uuid.uuid4()}", json={"status": "done"}, headers=api_key_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_todo_invalid_status(test_client, api_key_headers) -> None:
    """PATCH with an invalid status returns 422."""
    created = (
        await test_client.post(
            "/v1/todos", json={"description": "test"}, headers=api_key_headers
        )
    ).json()
    resp = await test_client.patch(
        f"/v1/todos/{created['id']}", json={"status": "pending"}, headers=api_key_headers
    )
    assert resp.status_code == 422


# ── GET /v1/todos/{id}/history ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_todo_history(test_client, api_key_headers) -> None:
    """GET /v1/todos/{id}/history returns all history rows oldest first."""
    created = (
        await test_client.post(
            "/v1/todos", json={"description": "trace me"}, headers=api_key_headers
        )
    ).json()
    todo_id = created["id"]

    # Apply two updates
    await test_client.patch(
        f"/v1/todos/{todo_id}", json={"priority": "high"}, headers=api_key_headers
    )
    await test_client.patch(
        f"/v1/todos/{todo_id}", json={"status": "done"}, headers=api_key_headers
    )

    resp = await test_client.get(f"/v1/todos/{todo_id}/history", headers=api_key_headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 3  # created + priority_changed + completed
    assert rows[0]["event_type"] == "created"


@pytest.mark.asyncio
async def test_history_append_only_invariant(test_client, api_key_headers) -> None:
    """Multiple PATCHes produce a monotonically growing history count."""
    created = (
        await test_client.post(
            "/v1/todos", json={"description": "monotone"}, headers=api_key_headers
        )
    ).json()
    todo_id = created["id"]

    history_url = f"/v1/todos/{todo_id}/history"

    def _count():
        # This is a sync helper — we'll use it after each await
        pass  # done inline below

    h1 = (await test_client.get(history_url, headers=api_key_headers)).json()
    assert len(h1) == 1  # just "created"

    await test_client.patch(f"/v1/todos/{todo_id}", json={"priority": "high"}, headers=api_key_headers)
    h2 = (await test_client.get(history_url, headers=api_key_headers)).json()
    assert len(h2) == 2

    await test_client.patch(f"/v1/todos/{todo_id}", json={"status": "cancelled"}, headers=api_key_headers)
    h3 = (await test_client.get(history_url, headers=api_key_headers)).json()
    assert len(h3) == 3


@pytest.mark.asyncio
async def test_get_history_todo_not_found(test_client, api_key_headers) -> None:
    """GET /v1/todos/{id}/history for non-existent todo returns 404."""
    resp = await test_client.get(f"/v1/todos/{uuid.uuid4()}/history", headers=api_key_headers)
    assert resp.status_code == 404


# ── Auth ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_todo_no_auth(test_client) -> None:
    """POST /v1/todos without auth header returns 401."""
    resp = await test_client.post("/v1/todos", json={"description": "test"})
    assert resp.status_code == 401


# ── Input Validation (Security) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_todo_fails_description_too_long(test_client, api_key_headers) -> None:
    """POST /v1/todos rejects description exceeding 500 chars with 422 (N1)."""
    resp = await test_client.post(
        "/v1/todos",
        json={"description": "x" * 501},
        headers=api_key_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_todo_fails_empty_description(test_client, api_key_headers) -> None:
    """POST /v1/todos rejects empty description with 422 (N1)."""
    resp = await test_client.post(
        "/v1/todos",
        json={"description": ""},
        headers=api_key_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_todo_fails_reason_too_long(test_client, api_key_headers) -> None:
    """PATCH /v1/todos/{id} rejects reason exceeding 500 chars with 422 (N1)."""
    # Create a todo first
    create_resp = await test_client.post(
        "/v1/todos",
        json={"description": "test todo"},
        headers=api_key_headers,
    )
    todo_id = create_resp.json()["id"]

    resp = await test_client.patch(
        f"/v1/todos/{todo_id}",
        json={"reason": "r" * 501},
        headers=api_key_headers,
    )
    assert resp.status_code == 422
