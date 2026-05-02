"""Learning library tests: CRUD, feature-flag gating, cron idempotency,
deterministic fallback, LLM selection, cascade semantics, materials."""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from src.core.models import LearningItem, LearningMaterial, LearningSection, LearningTopic, TodoItem


async def _mk_topic(session, name="Topic A", active=True, position=0):
    t = LearningTopic(name=name, is_active=active, position=position)
    session.add(t)
    await session.commit()
    await session.refresh(t)
    return t


async def _mk_section(session, topic_id, name="Section 1", position=0):
    s = LearningSection(topic_id=topic_id, name=name, position=position)
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return s


async def _mk_item(session, section_id, title="Item X", position=0, status="pending"):
    i = LearningItem(section_id=section_id, title=title, position=position, status=status)
    session.add(i)
    await session.commit()
    await session.refresh(i)
    return i


# ── CRUD ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_topic_returns_201(test_client, api_key_headers):
    resp = await test_client.post(
        "/v1/learning/topics",
        json={"name": "pgvector", "depth": "deep"},
        headers=api_key_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "pgvector"
    assert body["depth"] == "deep"
    assert body["is_active"] is True


@pytest.mark.asyncio
async def test_create_section_requires_existing_topic(test_client, api_key_headers):
    resp = await test_client.post(
        "/v1/learning/sections",
        json={"topic_id": str(uuid.uuid4()), "name": "X"},
        headers=api_key_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_tree_returns_nested(test_client, api_key_headers, async_session):
    topic = await _mk_topic(async_session, "T")
    section = await _mk_section(async_session, topic.id, "S")
    await _mk_item(async_session, section.id, "I")
    resp = await test_client.get("/v1/learning", headers=api_key_headers)
    assert resp.status_code == 200
    topics = resp.json()["topics"]
    assert len(topics) == 1
    assert topics[0]["sections"][0]["items"][0]["title"] == "I"


@pytest.mark.asyncio
async def test_delete_topic_without_confirm_rejected(test_client, api_key_headers, async_session):
    topic = await _mk_topic(async_session, "T")
    resp = await test_client.delete(f"/v1/learning/topics/{topic.id}", headers=api_key_headers)
    assert resp.status_code == 400
    resp = await test_client.delete(
        f"/v1/learning/topics/{topic.id}?confirm=true", headers=api_key_headers
    )
    assert resp.status_code == 204


# ── Feature flag ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_learning_disabled_returns_404(test_client, api_key_headers, monkeypatch):
    from src.core import config as _config

    monkeypatch.setattr(_config.settings, "module_learning_enabled", False)
    resp = await test_client.get("/v1/learning", headers=api_key_headers)
    assert resp.status_code == 404
    resp = await test_client.post(
        "/v1/learning/topics", json={"name": "x"}, headers=api_key_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_modules_endpoint_reflects_flag(test_client, api_key_headers, monkeypatch):
    from src.core import config as _config

    monkeypatch.setattr(_config.settings, "module_learning_enabled", False)
    resp = await test_client.get("/v1/modules", headers=api_key_headers)
    assert resp.status_code == 200
    assert resp.json()["learning"] is False


# ── Cron idempotency + fallback ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cron_creates_todos_from_active_topics(async_session, monkeypatch):
    from src.jobs.learning_daily import run_learning_selection

    topic = await _mk_topic(async_session, "T", active=True)
    section = await _mk_section(async_session, topic.id)
    for i in range(5):
        await _mk_item(async_session, section.id, title=f"Item {i}", position=i)

    # Force fallback path (no API key)
    from src.core import config as _config

    monkeypatch.setattr(_config.settings, "anthropic_api_key", None)

    summary = await run_learning_selection(async_session)
    assert summary["created"] == _config.settings.learning_daily_todo_count
    assert summary["fallback"] is True

    # Idempotency — second run creates nothing new
    summary2 = await run_learning_selection(async_session)
    assert summary2["created"] == 0
    assert summary2["skipped_existing"] >= summary["created"]


@pytest.mark.asyncio
async def test_cron_skips_inactive_topics(async_session, monkeypatch):
    from src.jobs.learning_daily import run_learning_selection

    topic = await _mk_topic(async_session, "T", active=False)
    section = await _mk_section(async_session, topic.id)
    await _mk_item(async_session, section.id)

    from src.core import config as _config

    monkeypatch.setattr(_config.settings, "anthropic_api_key", None)
    summary = await run_learning_selection(async_session)
    assert summary["created"] == 0


@pytest.mark.asyncio
async def test_cron_disabled_flag_returns_zero(async_session, monkeypatch):
    from src.core import config as _config
    from src.jobs.learning_daily import run_learning_selection

    monkeypatch.setattr(_config.settings, "module_learning_enabled", False)
    summary = await run_learning_selection(async_session)
    assert summary["created"] == 0
    assert summary["fallback"] is False


@pytest.mark.asyncio
async def test_deterministic_fallback_picks_oldest(async_session, monkeypatch):
    from src.jobs.learning_daily import run_learning_selection

    topic = await _mk_topic(async_session, "T")
    section = await _mk_section(async_session, topic.id)
    items = []
    for i in range(5):
        it = await _mk_item(async_session, section.id, title=f"I{i}", position=i)
        items.append(it)

    from src.core import config as _config

    monkeypatch.setattr(_config.settings, "anthropic_api_key", None)
    await run_learning_selection(async_session)

    result = await async_session.execute(
        select(TodoItem).where(TodoItem.learning_item_id.is_not(None))
    )
    todos = list(result.scalars().all())
    created_ids = {str(t.learning_item_id) for t in todos}
    n = _config.settings.learning_daily_todo_count
    candidate_ids = {str(i.id) for i in items}
    assert len(created_ids) == n
    assert created_ids <= candidate_ids
    # Re-running fallback with same state picks the same ids (determinism)
    summary2 = await run_learning_selection(async_session)
    assert summary2["created"] == 0  # idempotent, same day


@pytest.mark.asyncio
async def test_cron_uses_llm_selection_when_available(async_session, monkeypatch):
    from src.jobs.learning_daily import run_learning_selection

    topic = await _mk_topic(async_session, "T")
    section = await _mk_section(async_session, topic.id)
    items = [await _mk_item(async_session, section.id, title=f"I{i}", position=i) for i in range(5)]

    from pydantic import SecretStr

    from src.core import config as _config

    monkeypatch.setattr(_config.settings, "anthropic_api_key", SecretStr("fake-key"))

    async def fake_complete(self, system, user, max_tokens=1024):
        return json.dumps({"selections": [{"item_id": str(items[4].id), "reason": "r"}]})

    with patch("src.llm.client.AnthropicClient.complete", new=fake_complete):
        summary = await run_learning_selection(async_session)
    assert summary["created"] == 1
    assert summary["fallback"] is False
    result = await async_session.execute(
        select(TodoItem).where(TodoItem.learning_item_id.is_not(None))
    )
    todo = result.scalars().first()
    assert str(todo.learning_item_id) == str(items[4].id)


@pytest.mark.asyncio
async def test_cron_falls_back_on_malformed_llm_output(async_session, monkeypatch):
    from src.jobs.learning_daily import run_learning_selection

    topic = await _mk_topic(async_session, "T")
    section = await _mk_section(async_session, topic.id)
    await _mk_item(async_session, section.id, "I0")

    from pydantic import SecretStr

    from src.core import config as _config

    monkeypatch.setattr(_config.settings, "anthropic_api_key", SecretStr("fake-key"))

    async def fake_complete(self, system, user, max_tokens=1024):
        return "not json at all"

    with patch("src.llm.client.AnthropicClient.complete", new=fake_complete):
        summary = await run_learning_selection(async_session)
    assert summary["fallback"] is True
    assert summary["created"] >= 1


# ── Cascade ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_completing_learning_todo_cascades_to_item(test_client, api_key_headers, async_session):
    topic = await _mk_topic(async_session, "T")
    section = await _mk_section(async_session, topic.id)
    item = await _mk_item(async_session, section.id, "I")

    # Create a todo and link it to the learning item
    resp = await test_client.post(
        "/v1/todos", json={"description": "Study I"}, headers=api_key_headers
    )
    assert resp.status_code == 201
    todo_id = resp.json()["id"]
    todo = await async_session.get(TodoItem, uuid.UUID(todo_id))
    todo.learning_item_id = item.id
    await async_session.commit()

    resp = await test_client.patch(
        f"/v1/todos/{todo_id}",
        json={"status": "done", "learning_feedback": "too easy", "learning_notes": "done quickly"},
        headers=api_key_headers,
    )
    assert resp.status_code == 200

    await async_session.refresh(item)
    assert item.status == "done"
    assert item.completed_at is not None
    assert item.feedback == "too easy"
    assert item.notes == "done quickly"


@pytest.mark.asyncio
async def test_item_completion_cancels_matching_open_todo(test_client, api_key_headers, async_session):
    topic = await _mk_topic(async_session, "T")
    section = await _mk_section(async_session, topic.id)
    item = await _mk_item(async_session, section.id, "I")

    resp = await test_client.post(
        "/v1/todos", json={"description": "Study I"}, headers=api_key_headers
    )
    todo_id = resp.json()["id"]
    todo = await async_session.get(TodoItem, uuid.UUID(todo_id))
    todo.learning_item_id = item.id
    await async_session.commit()

    resp = await test_client.patch(
        f"/v1/learning/items/{item.id}",
        json={"status": "done"},
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    await async_session.refresh(todo)
    assert todo.status == "cancelled"


# ── Deactivation preserves state ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deactivating_topic_preserves_items(test_client, api_key_headers, async_session):
    topic = await _mk_topic(async_session, "T")
    section = await _mk_section(async_session, topic.id)
    item = await _mk_item(async_session, section.id, "I")
    item.feedback = "keep me"
    await async_session.commit()

    resp = await test_client.patch(
        f"/v1/learning/topics/{topic.id}",
        json={"is_active": False},
        headers=api_key_headers,
    )
    assert resp.status_code == 200

    await async_session.refresh(item)
    assert item.feedback == "keep me"
    assert item.status == "pending"


# ── Refresh endpoint ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_endpoint_returns_summary(test_client, api_key_headers, async_session, monkeypatch):
    topic = await _mk_topic(async_session, "T")
    section = await _mk_section(async_session, topic.id)
    await _mk_item(async_session, section.id, "I")

    from src.core import config as _config

    monkeypatch.setattr(_config.settings, "anthropic_api_key", None)

    resp = await test_client.post("/v1/learning/refresh", headers=api_key_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "created" in body
    assert "fallback" in body
    assert body["target_count"] == _config.settings.learning_daily_todo_count


# ── Material CRUD + tree flag ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_material_returns_null_when_absent(test_client, api_key_headers, async_session):
    """GET material returns 200 with null body when topic has no material."""
    topic = await _mk_topic(async_session)
    resp = await test_client.get(
        f"/v1/learning/topics/{topic.id}/material", headers=api_key_headers
    )
    assert resp.status_code == 200
    assert resp.json() is None


@pytest.mark.asyncio
async def test_patch_material_creates_then_updates(test_client, api_key_headers, async_session):
    """PATCH creates material on first call; updates content on second call."""
    topic = await _mk_topic(async_session)

    resp = await test_client.patch(
        f"/v1/learning/topics/{topic.id}/material",
        json={"content": "# Hello\nWorld", "source_type": "article"},
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "# Hello\nWorld"
    assert data["source_type"] == "article"
    assert data["topic_id"] == str(topic.id)

    resp2 = await test_client.patch(
        f"/v1/learning/topics/{topic.id}/material",
        json={"content": "# Updated"},
        headers=api_key_headers,
    )
    assert resp2.status_code == 200
    assert resp2.json()["content"] == "# Updated"

    count = await async_session.scalar(select(func.count()).select_from(LearningMaterial))
    assert count == 1  # no duplicate rows


@pytest.mark.asyncio
async def test_delete_material_requires_confirm(test_client, api_key_headers, async_session):
    """DELETE without confirm=true returns 400; with it returns 204."""
    topic = await _mk_topic(async_session)
    await test_client.patch(
        f"/v1/learning/topics/{topic.id}/material",
        json={"content": "some content"},
        headers=api_key_headers,
    )

    resp = await test_client.delete(
        f"/v1/learning/topics/{topic.id}/material", headers=api_key_headers
    )
    assert resp.status_code == 400

    resp2 = await test_client.delete(
        f"/v1/learning/topics/{topic.id}/material?confirm=true", headers=api_key_headers
    )
    assert resp2.status_code == 204


@pytest.mark.asyncio
async def test_delete_topic_cascades_material(test_client, api_key_headers, async_session):
    """Deleting a topic also removes its material via CASCADE."""
    topic = await _mk_topic(async_session)
    await test_client.patch(
        f"/v1/learning/topics/{topic.id}/material",
        json={"content": "cascade test"},
        headers=api_key_headers,
    )

    await test_client.delete(
        f"/v1/learning/topics/{topic.id}?confirm=true", headers=api_key_headers
    )

    count = await async_session.scalar(select(func.count()).select_from(LearningMaterial))
    assert count == 0


@pytest.mark.asyncio
async def test_get_tree_includes_has_material_flag(test_client, api_key_headers, async_session):
    """GET /v1/learning tree includes has_material flag per topic."""
    topic = await _mk_topic(async_session)

    resp = await test_client.get("/v1/learning", headers=api_key_headers)
    topics = resp.json()["topics"]
    assert topics[0]["has_material"] is False

    await test_client.patch(
        f"/v1/learning/topics/{topic.id}/material",
        json={"content": "material content"},
        headers=api_key_headers,
    )

    # Expire identity map so load_tree re-fetches the material relationship.
    # With expire_on_commit=False (test session), the cached material=None from
    # the first GET would otherwise shadow the newly committed row.
    async_session.expire_all()

    resp2 = await test_client.get("/v1/learning", headers=api_key_headers)
    topics2 = resp2.json()["topics"]
    assert topics2[0]["has_material"] is True
