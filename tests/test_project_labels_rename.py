"""Tests for the rename and DELETE-cascade behavior of /v1/project-labels.

Covers:
  - PATCH /v1/project-labels/{name} renames the label
  - Rename cascades to todo_items.project and memory_items.project
  - Color-only update (new_name omitted)
  - 409 on collision with another existing label
  - 404 when the source label does not exist
  - DELETE cascades to NULL on todo_items.project and memory_items.project
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from src.core.models import MemoryItem, ProjectLabel, RawMemory, TodoItem


async def _seed_label(test_client, api_key_headers, name: str, color: str = "#6750A4") -> None:
    resp = await test_client.post(
        "/v1/project-labels", json={"name": name, "color": color}, headers=api_key_headers
    )
    assert resp.status_code == 201


async def _seed_memory_with_project(session, project: str, raw_text: str = "x") -> str:
    raw = RawMemory(source="manual", raw_text=raw_text, metadata_={})
    session.add(raw)
    await session.flush()
    item = MemoryItem(raw_id=raw.id, type="context", content=raw_text, project=project)
    session.add(item)
    await session.commit()
    return str(item.id)


# ── PATCH ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rename_project_label(test_client, api_key_headers) -> None:
    """PATCH renames the label and returns the new name."""
    await _seed_label(test_client, api_key_headers, "OB")

    resp = await test_client.patch(
        "/v1/project-labels/OB",
        json={"new_name": "Open Brain"},
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Open Brain"

    # Source name no longer exists; new name does.
    labels = (await test_client.get("/v1/project-labels", headers=api_key_headers)).json()
    assert {lab["name"] for lab in labels} == {"Open Brain"}


@pytest.mark.asyncio
async def test_rename_cascades_to_todos_and_memories(
    test_client, api_key_headers, async_session
) -> None:
    """Renaming a label updates todo_items.project AND memory_items.project."""
    await _seed_label(test_client, api_key_headers, "OB")
    create = await test_client.post(
        "/v1/todos",
        json={"description": "task", "project": "OB"},
        headers=api_key_headers,
    )
    todo_id = create.json()["id"]
    memory_id = await _seed_memory_with_project(async_session, project="OB")

    resp = await test_client.patch(
        "/v1/project-labels/OB",
        json={"new_name": "Open Brain"},
        headers=api_key_headers,
    )
    assert resp.status_code == 200

    # Reload from a fresh perspective.
    todo = await async_session.get(TodoItem, uuid.UUID(todo_id))
    await async_session.refresh(todo)
    assert todo.project == "Open Brain"

    memory = await async_session.get(MemoryItem, uuid.UUID(memory_id))
    await async_session.refresh(memory)
    assert memory.project == "Open Brain"


@pytest.mark.asyncio
async def test_rename_color_only(test_client, api_key_headers, async_session) -> None:
    """PATCH with only color leaves the name intact and updates color."""
    await _seed_label(test_client, api_key_headers, "Health", color="#0D652D")

    resp = await test_client.patch(
        "/v1/project-labels/Health",
        json={"color": "#E07060"},
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Health"
    assert body["color"] == "#E07060"


@pytest.mark.asyncio
async def test_rename_collision_returns_409(test_client, api_key_headers, async_session) -> None:
    """PATCH with new_name matching another existing label returns 409, no mutation."""
    await _seed_label(test_client, api_key_headers, "OB")
    await _seed_label(test_client, api_key_headers, "Open Brain")
    await test_client.post(
        "/v1/todos",
        json={"description": "k", "project": "OB"},
        headers=api_key_headers,
    )

    resp = await test_client.patch(
        "/v1/project-labels/OB",
        json={"new_name": "Open Brain"},
        headers=api_key_headers,
    )
    assert resp.status_code == 409

    # OB still exists, todo still references OB.
    labels = (await test_client.get("/v1/project-labels", headers=api_key_headers)).json()
    assert {lab["name"] for lab in labels} == {"OB", "Open Brain"}

    todos = (await test_client.get("/v1/todos", headers=api_key_headers)).json()["todos"]
    assert any(t["project"] == "OB" for t in todos)


@pytest.mark.asyncio
async def test_rename_unknown_source_returns_404(test_client, api_key_headers) -> None:
    """PATCH against a non-existent label name returns 404."""
    resp = await test_client.patch(
        "/v1/project-labels/Phantom",
        json={"new_name": "Whatever"},
        headers=api_key_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rename_invalid_color_422(test_client, api_key_headers) -> None:
    """PATCH with non-hex color returns 422."""
    await _seed_label(test_client, api_key_headers, "Z")
    resp = await test_client.patch(
        "/v1/project-labels/Z", json={"color": "red"}, headers=api_key_headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_rename_to_same_name_is_noop(test_client, api_key_headers, async_session) -> None:
    """PATCH where new_name == current name does not error or duplicate-check."""
    await _seed_label(test_client, api_key_headers, "Same")
    resp = await test_client.patch(
        "/v1/project-labels/Same",
        json={"new_name": "Same"},
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Same"


# ── DELETE cascade ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_cascades_to_null(test_client, api_key_headers, async_session) -> None:
    """DELETE NULLs out todo_items.project and memory_items.project."""
    await _seed_label(test_client, api_key_headers, "OB")
    create = await test_client.post(
        "/v1/todos",
        json={"description": "k", "project": "OB"},
        headers=api_key_headers,
    )
    todo_id = create.json()["id"]
    memory_id = await _seed_memory_with_project(async_session, project="OB")

    resp = await test_client.delete("/v1/project-labels/OB", headers=api_key_headers)
    assert resp.status_code == 204

    todo = await async_session.get(TodoItem, uuid.UUID(todo_id))
    await async_session.refresh(todo)
    assert todo.project is None

    memory = await async_session.get(MemoryItem, uuid.UUID(memory_id))
    await async_session.refresh(memory)
    assert memory.project is None

    # Label row gone.
    remaining = (await async_session.execute(select(ProjectLabel))).scalars().all()
    assert all(lab.name != "OB" for lab in remaining)
