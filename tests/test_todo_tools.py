"""Tests for todo_service.list_todos and todo tool handlers."""

import json
import uuid

import pytest


# ── list_todos service tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_todos_returns_all(async_session):
    from src.api.services.todo_service import create_todo, list_todos

    await create_todo(async_session, description="Buy milk")
    await create_todo(async_session, description="Write tests")

    todos = await list_todos(async_session)
    descriptions = [t.description for t in todos]
    assert "Buy milk" in descriptions
    assert "Write tests" in descriptions


@pytest.mark.asyncio
async def test_list_todos_filter_status(async_session):
    from src.api.services.todo_service import create_todo, list_todos, update_todo

    t1 = await create_todo(async_session, description="Open task")
    t2 = await create_todo(async_session, description="Done task")
    await update_todo(async_session, t2, status="done")

    open_todos = await list_todos(async_session, status="open")
    assert all(t.status == "open" for t in open_todos)

    done_todos = await list_todos(async_session, status="done")
    assert any(t.description == "Done task" for t in done_todos)


@pytest.mark.asyncio
async def test_list_todos_filter_project(async_session):
    from src.api.services.todo_service import create_todo, list_todos

    await create_todo(async_session, description="Proj A task", project="proj-a")
    await create_todo(async_session, description="Proj B task", project="proj-b")

    results = await list_todos(async_session, project="proj-a")
    assert all(t.project == "proj-a" for t in results)
    assert len(results) >= 1


# ── Todo tool handler tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_list_todos(async_session):
    from src.api.services.todo_service import create_todo
    from src.api.services.todo_tools import handle_list_todos

    await create_todo(async_session, description="Feed the cat")
    out = await handle_list_todos("list_todos", {}, async_session, uuid.UUID(int=0))
    data = json.loads(out)
    assert any(t["description"] == "Feed the cat" for t in data)


@pytest.mark.asyncio
async def test_handle_create_todo(async_session):
    from src.api.services.todo_tools import handle_create_todo

    out = await handle_create_todo(
        "create_todo",
        {"description": "Write unit tests", "priority": "high"},
        async_session,
        uuid.UUID(int=0),
    )
    data = json.loads(out)
    assert data["description"] == "Write unit tests"
    assert "id" in data


@pytest.mark.asyncio
async def test_handle_complete_todo(async_session):
    from src.api.services.todo_service import create_todo
    from src.api.services.todo_tools import handle_complete_todo

    todo = await create_todo(async_session, description="Finish report")
    out = await handle_complete_todo(
        "complete_todo",
        {"todo_id": str(todo.id)},
        async_session,
        uuid.UUID(int=0),
    )
    assert "Finish report" in out and "done" in out.lower()


@pytest.mark.asyncio
async def test_handle_complete_todo_not_found(async_session):
    from src.api.services.todo_tools import handle_complete_todo
    from src.llm.tool_agent import ToolError

    with pytest.raises(ToolError, match="not found"):
        await handle_complete_todo(
            "complete_todo",
            {"todo_id": str(uuid.uuid4())},
            async_session,
            uuid.UUID(int=0),
        )


@pytest.mark.asyncio
async def test_handle_defer_todo(async_session):
    from src.api.services.todo_service import create_todo
    from src.api.services.todo_tools import handle_defer_todo

    todo = await create_todo(async_session, description="Submit taxes")
    out = await handle_defer_todo(
        "defer_todo",
        {"todo_id": str(todo.id), "until_date": "2026-06-01"},
        async_session,
        uuid.UUID(int=0),
    )
    assert "Submit taxes" in out or "deferred" in out.lower()


@pytest.mark.asyncio
async def test_handle_edit_todo(async_session):
    from src.api.services.todo_service import create_todo
    from src.api.services.todo_tools import handle_edit_todo

    todo = await create_todo(async_session, description="Old description")
    out = await handle_edit_todo(
        "edit_todo",
        {"todo_id": str(todo.id), "description": "New description"},
        async_session,
        uuid.UUID(int=0),
    )
    assert "New description" in out or "updated" in out.lower()
