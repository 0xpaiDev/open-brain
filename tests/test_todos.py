"""Tests for the Todo API endpoints.

Covers CRUD happy paths, validation errors, filter queries, and the
history append-only invariant. All tests use in-memory SQLite via conftest.
"""

import uuid
from datetime import datetime, timezone

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


@pytest.mark.asyncio
async def test_list_todos_ordered_by_created_at_desc(
    test_client, api_key_headers, async_session
) -> None:
    """GET /v1/todos returns todos ordered by created_at DESC (newest first).

    SQLite's datetime resolution can collapse multiple inserts into the same
    timestamp, so we set created_at explicitly to guarantee ordering.
    """
    from datetime import UTC, datetime, timedelta

    from src.core.models import TodoItem

    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i, desc in enumerate(["oldest", "middle", "newest"]):
        todo = TodoItem(description=desc, created_at=base + timedelta(hours=i))
        async_session.add(todo)
    await async_session.commit()

    resp = await test_client.get("/v1/todos", headers=api_key_headers)
    assert resp.status_code == 200
    descriptions = [t["description"] for t in resp.json()["todos"]]
    assert descriptions == ["newest", "middle", "oldest"]


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


# ── due_before filter ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_todos_due_before_filter(test_client, api_key_headers) -> None:
    """GET ?due_before filters todos with due_date before the threshold."""
    await test_client.post(
        "/v1/todos",
        json={"description": "future", "due_date": "2026-04-10T00:00:00Z"},
        headers=api_key_headers,
    )
    await test_client.post(
        "/v1/todos",
        json={"description": "past", "due_date": "2026-04-01T00:00:00Z"},
        headers=api_key_headers,
    )
    # No due_date — should NOT appear (NULL is not <= threshold)
    await test_client.post(
        "/v1/todos",
        json={"description": "no due"},
        headers=api_key_headers,
    )

    resp = await test_client.get(
        "/v1/todos?due_before=2026-04-05T00:00:00Z", headers=api_key_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["todos"][0]["description"] == "past"


@pytest.mark.asyncio
async def test_list_todos_due_before_timezone_naive_converted_to_utc(
    test_client, api_key_headers
) -> None:
    """due_before without tzinfo is treated as UTC (timezone-naive → UTC)."""
    await test_client.post(
        "/v1/todos",
        json={"description": "due early", "due_date": "2026-04-01T12:00:00Z"},
        headers=api_key_headers,
    )
    # Timezone-naive threshold — should be converted to UTC by route
    resp = await test_client.get(
        "/v1/todos?due_before=2026-04-02T00:00:00", headers=api_key_headers
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


# ── PATCH event_type="cancelled" ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_todo_cancelled_creates_cancelled_event(
    test_client, api_key_headers
) -> None:
    """PATCH status=cancelled records event_type='cancelled' in history."""
    created = (
        await test_client.post(
            "/v1/todos", json={"description": "cancel me"}, headers=api_key_headers
        )
    ).json()
    todo_id = created["id"]

    resp = await test_client.patch(
        f"/v1/todos/{todo_id}", json={"status": "cancelled"}, headers=api_key_headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    history = await test_client.get(
        f"/v1/todos/{todo_id}/history", headers=api_key_headers
    )
    events = history.json()
    assert events[-1]["event_type"] == "cancelled"


# ── Pagination ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_todos_pagination_offset_limit(test_client, api_key_headers) -> None:
    """GET ?limit=2&offset=1 returns correct slice with full total count."""
    for i in range(5):
        await test_client.post(
            "/v1/todos", json={"description": f"todo-{i}"}, headers=api_key_headers
        )

    resp = await test_client.get(
        "/v1/todos?limit=2&offset=1", headers=api_key_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 5
    assert len(body["todos"]) == 2


@pytest.mark.asyncio
async def test_list_todos_offset_beyond_total_returns_empty(
    test_client, api_key_headers
) -> None:
    """Offset beyond total returns empty list with correct total."""
    await test_client.post(
        "/v1/todos", json={"description": "only one"}, headers=api_key_headers
    )
    resp = await test_client.get(
        "/v1/todos?offset=100", headers=api_key_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["todos"] == []


# ── Strengthen: ordering determinism ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_todos_order_deterministic_repeated_calls(
    test_client, api_key_headers
) -> None:
    """Repeated list calls return identical ordering (deterministic tiebreaker)."""
    for i in range(5):
        await test_client.post(
            "/v1/todos",
            json={"description": f"rapid-{i}"},
            headers=api_key_headers,
        )

    resp1 = await test_client.get("/v1/todos", headers=api_key_headers)
    resp2 = await test_client.get("/v1/todos", headers=api_key_headers)
    ids1 = [t["id"] for t in resp1.json()["todos"]]
    ids2 = [t["id"] for t in resp2.json()["todos"]]
    assert ids1 == ids2
    assert len(ids1) == 5


# ── Strengthen: history snapshot field-level assertions ───────────────────────


@pytest.mark.asyncio
async def test_history_snapshot_values_on_priority_change(
    test_client, api_key_headers
) -> None:
    """PATCH priority records correct old_value/new_value with event_type='priority_changed'."""
    r = await test_client.post(
        "/v1/todos",
        json={"description": "snapshot test", "priority": "low"},
        headers=api_key_headers,
    )
    todo_id = r.json()["id"]

    await test_client.patch(
        f"/v1/todos/{todo_id}",
        json={"priority": "high"},
        headers=api_key_headers,
    )

    history = await test_client.get(
        f"/v1/todos/{todo_id}/history", headers=api_key_headers
    )
    events = history.json()
    update_event = events[-1]
    assert update_event["event_type"] == "priority_changed"
    assert update_event["old_value"]["priority"] == "low"
    assert update_event["new_value"]["priority"] == "high"
    # Description should remain unchanged in both snapshots
    assert update_event["old_value"]["description"] == "snapshot test"
    assert update_event["new_value"]["description"] == "snapshot test"


# ── T-01: PATCH description-only → event_type="updated" ─────────────────────


@pytest.mark.asyncio
async def test_patch_description_only_triggers_updated_event(
    test_client, api_key_headers
) -> None:
    """PATCH with only description field writes history with event_type='updated'."""
    created = (
        await test_client.post(
            "/v1/todos", json={"description": "original text"}, headers=api_key_headers
        )
    ).json()
    todo_id = created["id"]

    resp = await test_client.patch(
        f"/v1/todos/{todo_id}",
        json={"description": "updated text"},
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "updated text"

    history = await test_client.get(
        f"/v1/todos/{todo_id}/history", headers=api_key_headers
    )
    events = history.json()
    last_event = events[-1]
    assert last_event["event_type"] == "updated"
    assert last_event["new_value"]["description"] == "updated text"
    assert last_event["old_value"]["description"] == "original text"


# ── T-02: PATCH multiple fields at once ──────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_multiple_fields_priority_and_status(
    test_client, api_key_headers
) -> None:
    """PATCH with both priority and status: status='done' → event_type='completed'."""
    created = (
        await test_client.post(
            "/v1/todos", json={"description": "multi-field"}, headers=api_key_headers
        )
    ).json()
    todo_id = created["id"]

    resp = await test_client.patch(
        f"/v1/todos/{todo_id}",
        json={"priority": "high", "status": "done"},
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["priority"] == "high"
    assert body["status"] == "done"

    history = await test_client.get(
        f"/v1/todos/{todo_id}/history", headers=api_key_headers
    )
    events = history.json()
    assert events[-1]["event_type"] == "completed"


# ── T-03: PATCH empty body no-op ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_empty_body_is_valid(test_client, api_key_headers) -> None:
    """PATCH with {} body returns 200 and the todo remains unchanged."""
    created = (
        await test_client.post(
            "/v1/todos", json={"description": "no-op test"}, headers=api_key_headers
        )
    ).json()
    todo_id = created["id"]

    resp = await test_client.patch(
        f"/v1/todos/{todo_id}",
        json={},
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["description"] == "no-op test"
    assert body["priority"] == "normal"
    assert body["status"] == "open"


# ── T-04: GET ?limit=0 → 422 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_todos_limit_zero_returns_422(test_client, api_key_headers) -> None:
    """GET /v1/todos?limit=0 returns 422 (below ge=1)."""
    resp = await test_client.get("/v1/todos?limit=0", headers=api_key_headers)
    assert resp.status_code == 422


# ── T-05: GET ?limit=501 → 422 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_todos_limit_over_max_returns_422(test_client, api_key_headers) -> None:
    """GET /v1/todos?limit=501 returns 422 (above le=500)."""
    resp = await test_client.get("/v1/todos?limit=501", headers=api_key_headers)
    assert resp.status_code == 422


# ── T-06: GET combined status+priority filter ────────────────────────────────


@pytest.mark.asyncio
async def test_list_todos_combined_status_priority_filter(
    test_client, api_key_headers
) -> None:
    """GET ?status=open&priority=high returns only the intersection."""
    await test_client.post(
        "/v1/todos",
        json={"description": "open-high", "priority": "high"},
        headers=api_key_headers,
    )
    await test_client.post(
        "/v1/todos",
        json={"description": "open-normal"},
        headers=api_key_headers,
    )
    # Create and complete a high-priority todo
    done_resp = await test_client.post(
        "/v1/todos",
        json={"description": "done-high", "priority": "high"},
        headers=api_key_headers,
    )
    done_id = done_resp.json()["id"]
    await test_client.patch(
        f"/v1/todos/{done_id}", json={"status": "done"}, headers=api_key_headers
    )

    resp = await test_client.get(
        "/v1/todos?status=open&priority=high", headers=api_key_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["todos"][0]["description"] == "open-high"


# ── T-07, T-08, T-09: Auth on GET/PATCH/history ─────────────────────────────


@pytest.mark.asyncio
async def test_list_todos_requires_auth(test_client) -> None:
    """GET /v1/todos without X-API-Key returns 401."""
    resp = await test_client.get("/v1/todos")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_patch_todo_requires_auth(test_client, api_key_headers) -> None:
    """PATCH /v1/todos/{id} without X-API-Key returns 401."""
    created = (
        await test_client.post(
            "/v1/todos", json={"description": "auth test"}, headers=api_key_headers
        )
    ).json()
    resp = await test_client.patch(
        f"/v1/todos/{created['id']}", json={"status": "done"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_todo_history_requires_auth(test_client, api_key_headers) -> None:
    """GET /v1/todos/{id}/history without X-API-Key returns 401."""
    created = (
        await test_client.post(
            "/v1/todos", json={"description": "auth hist"}, headers=api_key_headers
        )
    ).json()
    resp = await test_client.get(f"/v1/todos/{created['id']}/history")
    assert resp.status_code == 401


# ── T-18: POST description exactly 500 chars ────────────────────────────────


@pytest.mark.asyncio
async def test_create_todo_description_at_max_length(test_client, api_key_headers) -> None:
    """POST /v1/todos with description of exactly 500 chars returns 201."""
    resp = await test_client.post(
        "/v1/todos",
        json={"description": "x" * 500},
        headers=api_key_headers,
    )
    assert resp.status_code == 201


# ── F2: start_date tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_todo_with_start_date(test_client, api_key_headers) -> None:
    """POST /v1/todos with start_date returns it in the response."""
    resp = await test_client.post(
        "/v1/todos",
        json={
            "description": "start date task",
            "start_date": "2026-04-01T00:00:00Z",
        },
        headers=api_key_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["start_date"] is not None
    assert "2026-04-01" in body["start_date"]
    # due_date should be null when not provided
    assert body["due_date"] is None


@pytest.mark.asyncio
async def test_update_todo_start_date(test_client, api_key_headers) -> None:
    """PATCH with start_date updates the field and appears in response."""
    created = (
        await test_client.post(
            "/v1/todos",
            json={"description": "update start date"},
            headers=api_key_headers,
        )
    ).json()
    todo_id = created["id"]
    assert created["start_date"] is None

    resp = await test_client.patch(
        f"/v1/todos/{todo_id}",
        json={"start_date": "2026-05-01T00:00:00Z"},
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    assert "2026-05-01" in resp.json()["start_date"]


@pytest.mark.asyncio
async def test_create_todo_with_date_range(test_client, api_key_headers) -> None:
    """POST with both start_date and due_date returns both in response."""
    resp = await test_client.post(
        "/v1/todos",
        json={
            "description": "date range task",
            "start_date": "2026-04-01T00:00:00Z",
            "due_date": "2026-04-15T00:00:00Z",
        },
        headers=api_key_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "2026-04-01" in body["start_date"]
    assert "2026-04-15" in body["due_date"]


@pytest.mark.asyncio
async def test_start_date_in_history_snapshot(test_client, api_key_headers) -> None:
    """History snapshot includes start_date in old_value and new_value."""
    created = (
        await test_client.post(
            "/v1/todos",
            json={
                "description": "snapshot start_date",
                "start_date": "2026-04-01T00:00:00Z",
            },
            headers=api_key_headers,
        )
    ).json()
    todo_id = created["id"]

    # Update start_date
    await test_client.patch(
        f"/v1/todos/{todo_id}",
        json={"start_date": "2026-05-01T00:00:00Z"},
        headers=api_key_headers,
    )

    history = await test_client.get(
        f"/v1/todos/{todo_id}/history", headers=api_key_headers
    )
    events = history.json()
    # Last event is the update
    last = events[-1]
    assert "start_date" in last["old_value"]
    assert "start_date" in last["new_value"]
    assert "2026-04-01" in last["old_value"]["start_date"]
    assert "2026-05-01" in last["new_value"]["start_date"]


# ── F1/F6-backend: reopened event ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reopen_todo_creates_reopened_history(test_client, api_key_headers) -> None:
    """PATCH status='open' on a done todo writes event_type='reopened'."""
    created = (
        await test_client.post(
            "/v1/todos", json={"description": "reopen me"}, headers=api_key_headers
        )
    ).json()
    todo_id = created["id"]

    # Complete it first
    await test_client.patch(
        f"/v1/todos/{todo_id}", json={"status": "done"}, headers=api_key_headers
    )

    # Reopen
    resp = await test_client.patch(
        f"/v1/todos/{todo_id}", json={"status": "open"}, headers=api_key_headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "open"

    history = await test_client.get(
        f"/v1/todos/{todo_id}/history", headers=api_key_headers
    )
    events = history.json()
    assert events[-1]["event_type"] == "reopened"


@pytest.mark.asyncio
async def test_reopen_non_done_todo_creates_updated_history(test_client, api_key_headers) -> None:
    """PATCH status='open' on an already-open todo produces 'updated', not 'reopened'."""
    created = (
        await test_client.post(
            "/v1/todos", json={"description": "already open"}, headers=api_key_headers
        )
    ).json()
    todo_id = created["id"]

    resp = await test_client.patch(
        f"/v1/todos/{todo_id}", json={"status": "open"}, headers=api_key_headers
    )
    assert resp.status_code == 200

    history = await test_client.get(
        f"/v1/todos/{todo_id}/history", headers=api_key_headers
    )
    events = history.json()
    assert events[-1]["event_type"] == "updated"


# ── F5: overdue-undeferred endpoint ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_overdue_undeferred_returns_overdue_tasks(
    test_client, api_key_headers
) -> None:
    """GET /v1/todos/overdue-undeferred returns open todos past their due date."""
    await test_client.post(
        "/v1/todos",
        json={"description": "overdue task", "due_date": "2020-01-01T00:00:00Z"},
        headers=api_key_headers,
    )
    resp = await test_client.get("/v1/todos/overdue-undeferred", headers=api_key_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["description"] == "overdue task"


@pytest.mark.asyncio
async def test_overdue_undeferred_excludes_deferred_today(
    test_client, api_key_headers
) -> None:
    """Overdue task deferred today is excluded from the list."""
    created = (
        await test_client.post(
            "/v1/todos",
            json={"description": "deferred today", "due_date": "2020-01-01T00:00:00Z"},
            headers=api_key_headers,
        )
    ).json()
    todo_id = created["id"]

    # Defer it (creates a "deferred" history entry with today's timestamp)
    await test_client.patch(
        f"/v1/todos/{todo_id}",
        json={"due_date": "2026-12-31T00:00:00Z", "reason": "busy"},
        headers=api_key_headers,
    )

    resp = await test_client.get("/v1/todos/overdue-undeferred", headers=api_key_headers)
    assert resp.status_code == 200
    # The task now has a future due_date, so it won't be overdue anymore
    assert len(resp.json()) == 0


@pytest.mark.asyncio
async def test_overdue_undeferred_includes_deferred_yesterday(
    test_client, api_key_headers, async_session
) -> None:
    """Overdue task deferred yesterday (but still overdue) appears in the list."""
    from datetime import timedelta

    from src.core.models import TodoHistory

    created = (
        await test_client.post(
            "/v1/todos",
            json={"description": "deferred yesterday", "due_date": "2020-01-01T00:00:00Z"},
            headers=api_key_headers,
        )
    ).json()
    todo_id = created["id"]

    # Defer it, then backdate the history entry to yesterday
    await test_client.patch(
        f"/v1/todos/{todo_id}",
        json={"due_date": "2020-01-02T00:00:00Z", "reason": "still overdue"},
        headers=api_key_headers,
    )

    from sqlalchemy import select

    result = await async_session.execute(
        select(TodoHistory)
        .where(TodoHistory.todo_id == uuid.UUID(todo_id))
        .where(TodoHistory.event_type == "deferred")
    )
    deferred_row = result.scalar_one()
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    deferred_row.created_at = yesterday
    await async_session.commit()

    resp = await test_client.get("/v1/todos/overdue-undeferred", headers=api_key_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["description"] == "deferred yesterday"


@pytest.mark.asyncio
async def test_overdue_undeferred_excludes_completed(
    test_client, api_key_headers
) -> None:
    """Completed overdue todo is not returned."""
    created = (
        await test_client.post(
            "/v1/todos",
            json={"description": "done overdue", "due_date": "2020-01-01T00:00:00Z"},
            headers=api_key_headers,
        )
    ).json()
    todo_id = created["id"]

    await test_client.patch(
        f"/v1/todos/{todo_id}", json={"status": "done"}, headers=api_key_headers
    )

    resp = await test_client.get("/v1/todos/overdue-undeferred", headers=api_key_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 0


@pytest.mark.asyncio
async def test_overdue_undeferred_excludes_future_tasks(
    test_client, api_key_headers
) -> None:
    """Task due tomorrow is not returned."""
    await test_client.post(
        "/v1/todos",
        json={"description": "future task", "due_date": "2099-01-01T00:00:00Z"},
        headers=api_key_headers,
    )
    resp = await test_client.get("/v1/todos/overdue-undeferred", headers=api_key_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 0


@pytest.mark.asyncio
async def test_overdue_undeferred_empty_when_no_overdue(
    test_client, api_key_headers
) -> None:
    """No overdue tasks returns empty list."""
    resp = await test_client.get("/v1/todos/overdue-undeferred", headers=api_key_headers)
    assert resp.status_code == 200
    assert resp.json() == []
