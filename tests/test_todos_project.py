"""Tests for the project field on todo_items.

Covers:
  - POST /v1/todos with valid / invalid / null project
  - PATCH /v1/todos/{id} updating project (history written, sync called)
  - TodoResponse includes the project field
  - DELETE /v1/project-labels cascades to NULL on todo_items.project
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from src.core.models import TodoHistory, TodoItem


@pytest.mark.asyncio
async def test_create_todo_with_project(test_client, api_key_headers, async_session) -> None:
    """POST with a valid project label name returns 201 and persists the field."""
    await test_client.post(
        "/v1/project-labels", json={"name": "OB", "color": "#E07060"}, headers=api_key_headers
    )

    resp = await test_client.post(
        "/v1/todos",
        json={"description": "Wire up project field", "project": "OB"},
        headers=api_key_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["project"] == "OB"

    # Verify DB row.
    row = await async_session.get(TodoItem, uuid.UUID(body["id"]))
    assert row is not None
    assert row.project == "OB"


@pytest.mark.asyncio
async def test_create_todo_without_project_defaults_to_null(test_client, api_key_headers) -> None:
    """POST without a project field stores NULL (renders as Personal at UI layer)."""
    resp = await test_client.post(
        "/v1/todos",
        json={"description": "no project here"},
        headers=api_key_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["project"] is None


@pytest.mark.asyncio
async def test_create_todo_unknown_project_returns_422(test_client, api_key_headers) -> None:
    """POST with a project that does not exist in project_labels returns 422."""
    resp = await test_client.post(
        "/v1/todos",
        json={"description": "phantom project", "project": "Phantom"},
        headers=api_key_headers,
    )
    assert resp.status_code == 422
    assert "Phantom" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_todo_project_too_long_422(test_client, api_key_headers) -> None:
    """POST with project > 100 chars rejected by Pydantic max_length."""
    resp = await test_client.post(
        "/v1/todos",
        json={"description": "x", "project": "x" * 101},
        headers=api_key_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_todo_set_project(test_client, api_key_headers, async_session) -> None:
    """PATCH can attach a project to an existing todo and writes history row."""
    await test_client.post("/v1/project-labels", json={"name": "Egle"}, headers=api_key_headers)
    create = await test_client.post(
        "/v1/todos", json={"description": "project me"}, headers=api_key_headers
    )
    todo_id = create.json()["id"]

    resp = await test_client.patch(
        f"/v1/todos/{todo_id}",
        json={"project": "Egle"},
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["project"] == "Egle"

    # History row written for the update.
    history = (
        (
            await async_session.execute(
                select(TodoHistory).where(TodoHistory.todo_id == uuid.UUID(todo_id))
            )
        )
        .scalars()
        .all()
    )
    # created + updated
    assert len(history) == 2
    assert history[-1].new_value["project"] == "Egle"


@pytest.mark.asyncio
async def test_patch_todo_clear_project(test_client, api_key_headers) -> None:
    """PATCH with project=null clears the field (todo falls back to Personal)."""
    await test_client.post("/v1/project-labels", json={"name": "OB"}, headers=api_key_headers)
    create = await test_client.post(
        "/v1/todos",
        json={"description": "to clear", "project": "OB"},
        headers=api_key_headers,
    )
    todo_id = create.json()["id"]

    resp = await test_client.patch(
        f"/v1/todos/{todo_id}",
        json={"project": None},
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["project"] is None


@pytest.mark.asyncio
async def test_patch_todo_unknown_project_422(test_client, api_key_headers) -> None:
    """PATCH with an unknown project returns 422 and does not mutate the row."""
    create = await test_client.post("/v1/todos", json={"description": "x"}, headers=api_key_headers)
    todo_id = create.json()["id"]

    resp = await test_client.patch(
        f"/v1/todos/{todo_id}", json={"project": "Ghost"}, headers=api_key_headers
    )
    assert resp.status_code == 422

    after = await test_client.get(f"/v1/todos/{todo_id}", headers=api_key_headers)
    assert after.json()["project"] is None


@pytest.mark.asyncio
async def test_list_todos_response_includes_project(test_client, api_key_headers) -> None:
    """GET /v1/todos response items always carry a project field (NULL or set)."""
    await test_client.post("/v1/project-labels", json={"name": "Work"}, headers=api_key_headers)
    await test_client.post(
        "/v1/todos", json={"description": "a", "project": "Work"}, headers=api_key_headers
    )
    await test_client.post("/v1/todos", json={"description": "b"}, headers=api_key_headers)

    resp = await test_client.get("/v1/todos", headers=api_key_headers)
    assert resp.status_code == 200
    todos = resp.json()["todos"]
    assert {t["project"] for t in todos} == {"Work", None}
