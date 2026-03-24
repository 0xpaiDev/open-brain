"""Tests for Phase 2.4: entity alias and merge endpoints.

Covers:
  GET  /v1/entities
  GET  /v1/entities/{entity_id}
  POST /v1/entities/merge
  POST /v1/entities/{entity_id}/aliases
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.core.models import Entity, EntityAlias, EntityRelation, MemoryEntityLink, MemoryItem, RawMemory


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
async def entity_a(async_session) -> Entity:
    """Entity 'Anthropic' (org) with two aliases."""
    entity = Entity(name="Anthropic", type="org")
    async_session.add(entity)
    await async_session.flush()
    alias1 = EntityAlias(entity_id=entity.id, alias="anthropic inc", source="api")
    alias2 = EntityAlias(entity_id=entity.id, alias="ANTH", source="api")
    async_session.add(alias1)
    async_session.add(alias2)
    await async_session.flush()
    await async_session.commit()
    await async_session.refresh(entity)
    return entity


@pytest_asyncio.fixture
async def entity_b(async_session) -> Entity:
    """Entity 'Anthropic Inc' (org) — merge source."""
    entity = Entity(name="Anthropic Inc", type="org")
    async_session.add(entity)
    await async_session.flush()
    await async_session.commit()
    return entity


@pytest_asyncio.fixture
async def entity_c(async_session) -> Entity:
    """Entity 'Claude' (project)."""
    entity = Entity(name="Claude", type="project")
    async_session.add(entity)
    await async_session.flush()
    await async_session.commit()
    return entity


# ── GET /v1/entities ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_entities_returns_200_with_entities(client, auth_headers, entity_a):
    resp = await client.get("/v1/entities", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    names = [e["name"] for e in body["entities"]]
    assert "Anthropic" in names


@pytest.mark.asyncio
async def test_list_entities_empty_returns_empty_list(client, auth_headers):
    resp = await client.get("/v1/entities", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["entities"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_list_entities_q_filter_matches_substring(client, auth_headers, entity_a, entity_c):
    resp = await client.get("/v1/entities?q=anthro", headers=auth_headers)
    assert resp.status_code == 200
    names = [e["name"] for e in resp.json()["entities"]]
    assert "Anthropic" in names
    assert "Claude" not in names


@pytest.mark.asyncio
async def test_list_entities_q_filter_case_insensitive(client, auth_headers, entity_a):
    resp = await client.get("/v1/entities?q=ANTHROPIC", headers=auth_headers)
    assert resp.status_code == 200
    names = [e["name"] for e in resp.json()["entities"]]
    assert "Anthropic" in names


@pytest.mark.asyncio
async def test_list_entities_type_filter(client, auth_headers, entity_a, entity_c):
    resp = await client.get("/v1/entities?type_filter=project", headers=auth_headers)
    assert resp.status_code == 200
    types = [e["type"] for e in resp.json()["entities"]]
    assert all(t == "project" for t in types)
    assert "Claude" in [e["name"] for e in resp.json()["entities"]]


@pytest.mark.asyncio
async def test_list_entities_includes_aliases(client, auth_headers, entity_a):
    resp = await client.get("/v1/entities", headers=auth_headers)
    assert resp.status_code == 200
    anthropic = next(e for e in resp.json()["entities"] if e["name"] == "Anthropic")
    alias_strings = [a["alias"] for a in anthropic["aliases"]]
    assert "anthropic inc" in alias_strings
    assert "ANTH" in alias_strings


@pytest.mark.asyncio
async def test_list_entities_limit(client, auth_headers, entity_a, entity_b, entity_c):
    resp = await client.get("/v1/entities?limit=2", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()["entities"]) <= 2


@pytest.mark.asyncio
async def test_list_entities_requires_auth(client):
    resp = await client.get("/v1/entities")
    assert resp.status_code == 401


# ── GET /v1/entities/{entity_id} ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_entity_returns_entity_with_aliases(client, auth_headers, entity_a):
    resp = await client.get(f"/v1/entities/{entity_a.id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Anthropic"
    assert body["type"] == "org"
    assert len(body["aliases"]) == 2


@pytest.mark.asyncio
async def test_get_entity_not_found_returns_404(client, auth_headers):
    resp = await client.get(f"/v1/entities/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_entity_invalid_uuid_returns_422(client, auth_headers):
    resp = await client.get("/v1/entities/not-a-uuid", headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_entity_requires_auth(client, entity_a):
    resp = await client.get(f"/v1/entities/{entity_a.id}")
    assert resp.status_code == 401


# ── POST /v1/entities/{entity_id}/aliases ─────────────────────────────────────


@pytest.mark.asyncio
async def test_add_alias_returns_201_with_alias_data(client, auth_headers, entity_a):
    resp = await client.post(
        f"/v1/entities/{entity_a.id}/aliases",
        json={"alias": "new-alias"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["alias"] == "new-alias"
    assert body["entity_id"] == str(entity_a.id)


@pytest.mark.asyncio
async def test_add_alias_persists_in_db(client, auth_headers, entity_a, async_session):
    await client.post(
        f"/v1/entities/{entity_a.id}/aliases",
        json={"alias": "persisted-alias"},
        headers=auth_headers,
    )
    result = await async_session.execute(
        select(EntityAlias).where(EntityAlias.alias == "persisted-alias")
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert str(row.entity_id) == str(entity_a.id)


@pytest.mark.asyncio
async def test_add_alias_entity_not_found_returns_404(client, auth_headers):
    resp = await client.post(
        f"/v1/entities/{uuid.uuid4()}/aliases",
        json={"alias": "orphan-alias"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_add_alias_duplicate_on_same_entity_returns_409(client, auth_headers, entity_a):
    await client.post(
        f"/v1/entities/{entity_a.id}/aliases",
        json={"alias": "dup-alias"},
        headers=auth_headers,
    )
    resp2 = await client.post(
        f"/v1/entities/{entity_a.id}/aliases",
        json={"alias": "dup-alias"},
        headers=auth_headers,
    )
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_add_alias_stolen_by_other_entity_returns_409(client, auth_headers, entity_a, entity_b):
    # entity_a claims the alias first
    await client.post(
        f"/v1/entities/{entity_a.id}/aliases",
        json={"alias": "contested-alias"},
        headers=auth_headers,
    )
    # entity_b tries to claim the same alias
    resp = await client.post(
        f"/v1/entities/{entity_b.id}/aliases",
        json={"alias": "contested-alias"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_add_alias_invalid_entity_uuid_returns_422(client, auth_headers):
    resp = await client.post(
        "/v1/entities/not-a-uuid/aliases",
        json={"alias": "some-alias"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_add_alias_with_source_persists_source(client, auth_headers, entity_a, async_session):
    await client.post(
        f"/v1/entities/{entity_a.id}/aliases",
        json={"alias": "sourced-alias", "source": "manual"},
        headers=auth_headers,
    )
    result = await async_session.execute(
        select(EntityAlias).where(EntityAlias.alias == "sourced-alias")
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.source == "manual"


@pytest.mark.asyncio
async def test_add_alias_requires_auth(client, entity_a):
    resp = await client.post(
        f"/v1/entities/{entity_a.id}/aliases",
        json={"alias": "no-auth-alias"},
    )
    assert resp.status_code == 401


# ── POST /v1/entities/merge ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_merge_entities_returns_200_with_counts(client, auth_headers, entity_a, entity_b):
    resp = await client.post(
        "/v1/entities/merge",
        json={"source_entity_id": str(entity_b.id), "target_entity_id": str(entity_a.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["target_entity_id"] == str(entity_a.id)
    assert "aliases_moved" in body
    assert "memory_links_moved" in body
    assert "relations_moved" in body


@pytest.mark.asyncio
async def test_merge_entities_deletes_source(client, auth_headers, entity_a, entity_b):
    await client.post(
        "/v1/entities/merge",
        json={"source_entity_id": str(entity_b.id), "target_entity_id": str(entity_a.id)},
        headers=auth_headers,
    )
    resp = await client.get(f"/v1/entities/{entity_b.id}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_merge_entities_moves_aliases_to_target(client, auth_headers, entity_a, entity_b, async_session):
    # Give entity_b an alias
    alias = EntityAlias(entity_id=entity_b.id, alias="b-unique-alias", source="api")
    async_session.add(alias)
    await async_session.commit()

    await client.post(
        "/v1/entities/merge",
        json={"source_entity_id": str(entity_b.id), "target_entity_id": str(entity_a.id)},
        headers=auth_headers,
    )

    result = await async_session.execute(
        select(EntityAlias).where(EntityAlias.alias == "b-unique-alias")
    )
    moved = result.scalar_one_or_none()
    assert moved is not None
    assert str(moved.entity_id) == str(entity_a.id)


@pytest.mark.asyncio
async def test_merge_entities_adds_source_name_as_alias(client, auth_headers, entity_a, entity_b, async_session):
    source_name = entity_b.name  # "Anthropic Inc"

    await client.post(
        "/v1/entities/merge",
        json={"source_entity_id": str(entity_b.id), "target_entity_id": str(entity_a.id)},
        headers=auth_headers,
    )

    result = await async_session.execute(
        select(EntityAlias).where(EntityAlias.alias == source_name)
    )
    alias = result.scalar_one_or_none()
    assert alias is not None
    assert str(alias.entity_id) == str(entity_a.id)


@pytest.mark.asyncio
async def test_merge_entities_source_name_already_aliased_no_error(
    client, auth_headers, entity_a, entity_b, async_session
):
    """Merge succeeds even if target already has source.name as an alias."""
    existing = EntityAlias(entity_id=entity_a.id, alias=entity_b.name, source="api")
    async_session.add(existing)
    await async_session.commit()

    resp = await client.post(
        "/v1/entities/merge",
        json={"source_entity_id": str(entity_b.id), "target_entity_id": str(entity_a.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["source_name_aliased"] is False


@pytest.mark.asyncio
async def test_merge_entities_moves_memory_links(
    client, auth_headers, entity_a, entity_b, async_session
):
    """Memory links from source entity move to target after merge."""
    raw = RawMemory(source="api", raw_text="linked memory")
    async_session.add(raw)
    await async_session.flush()
    item = MemoryItem(raw_id=raw.id, type="memory", content="linked", embedding=[0.0] * 1024)
    async_session.add(item)
    await async_session.flush()
    link = MemoryEntityLink(memory_id=item.id, entity_id=entity_b.id)
    async_session.add(link)
    await async_session.commit()

    await client.post(
        "/v1/entities/merge",
        json={"source_entity_id": str(entity_b.id), "target_entity_id": str(entity_a.id)},
        headers=auth_headers,
    )

    result = await async_session.execute(
        select(MemoryEntityLink).where(
            MemoryEntityLink.memory_id == item.id,
            MemoryEntityLink.entity_id == entity_a.id,
        )
    )
    assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_merge_entities_deduplicates_memory_links_on_conflict(
    client, auth_headers, entity_a, entity_b, async_session
):
    """When both entities share a memory link, merge deduplicates — one link remains."""
    raw = RawMemory(source="api", raw_text="shared memory")
    async_session.add(raw)
    await async_session.flush()
    item = MemoryItem(raw_id=raw.id, type="memory", content="shared", embedding=[0.0] * 1024)
    async_session.add(item)
    await async_session.flush()
    link_a = MemoryEntityLink(memory_id=item.id, entity_id=entity_a.id)
    link_b = MemoryEntityLink(memory_id=item.id, entity_id=entity_b.id)
    async_session.add(link_a)
    async_session.add(link_b)
    await async_session.commit()

    resp = await client.post(
        "/v1/entities/merge",
        json={"source_entity_id": str(entity_b.id), "target_entity_id": str(entity_a.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    result = await async_session.execute(
        select(MemoryEntityLink).where(MemoryEntityLink.memory_id == item.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert str(rows[0].entity_id) == str(entity_a.id)


@pytest.mark.asyncio
async def test_merge_entities_moves_relations_from_direction(
    client, auth_headers, entity_a, entity_b, entity_c, async_session
):
    """Outgoing relations from source are reassigned to target after merge."""
    raw = RawMemory(source="api", raw_text="relation context")
    async_session.add(raw)
    await async_session.flush()
    item = MemoryItem(raw_id=raw.id, type="memory", content="rel", embedding=[0.0] * 1024)
    async_session.add(item)
    await async_session.flush()
    rel = EntityRelation(
        from_entity_id=entity_b.id,
        to_entity_id=entity_c.id,
        relation_type="works_on",
        memory_id=item.id,
    )
    async_session.add(rel)
    await async_session.commit()

    await client.post(
        "/v1/entities/merge",
        json={"source_entity_id": str(entity_b.id), "target_entity_id": str(entity_a.id)},
        headers=auth_headers,
    )

    result = await async_session.execute(
        select(EntityRelation).where(
            EntityRelation.from_entity_id == entity_a.id,
            EntityRelation.to_entity_id == entity_c.id,
        )
    )
    assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_merge_entities_moves_relations_to_direction(
    client, auth_headers, entity_a, entity_b, entity_c, async_session
):
    """Incoming relations to source are reassigned to target after merge."""
    raw = RawMemory(source="api", raw_text="incoming rel")
    async_session.add(raw)
    await async_session.flush()
    item = MemoryItem(raw_id=raw.id, type="memory", content="inc rel", embedding=[0.0] * 1024)
    async_session.add(item)
    await async_session.flush()
    rel = EntityRelation(
        from_entity_id=entity_c.id,
        to_entity_id=entity_b.id,
        relation_type="related_to",
        memory_id=item.id,
    )
    async_session.add(rel)
    await async_session.commit()

    await client.post(
        "/v1/entities/merge",
        json={"source_entity_id": str(entity_b.id), "target_entity_id": str(entity_a.id)},
        headers=auth_headers,
    )

    result = await async_session.execute(
        select(EntityRelation).where(
            EntityRelation.from_entity_id == entity_c.id,
            EntityRelation.to_entity_id == entity_a.id,
        )
    )
    assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_merge_entities_deduplicates_relations_on_conflict(
    client, auth_headers, entity_a, entity_b, entity_c, async_session
):
    """Duplicate relations (same target+type+memory) are resolved — one remains."""
    raw = RawMemory(source="api", raw_text="dup rel")
    async_session.add(raw)
    await async_session.flush()
    item = MemoryItem(raw_id=raw.id, type="memory", content="dup", embedding=[0.0] * 1024)
    async_session.add(item)
    await async_session.flush()
    # Both entity_a and entity_b point to entity_c with same type+memory
    rel_a = EntityRelation(
        from_entity_id=entity_a.id,
        to_entity_id=entity_c.id,
        relation_type="owns",
        memory_id=item.id,
    )
    rel_b = EntityRelation(
        from_entity_id=entity_b.id,
        to_entity_id=entity_c.id,
        relation_type="owns",
        memory_id=item.id,
    )
    async_session.add(rel_a)
    async_session.add(rel_b)
    await async_session.commit()

    resp = await client.post(
        "/v1/entities/merge",
        json={"source_entity_id": str(entity_b.id), "target_entity_id": str(entity_a.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    result = await async_session.execute(
        select(EntityRelation).where(
            EntityRelation.from_entity_id == entity_a.id,
            EntityRelation.to_entity_id == entity_c.id,
            EntityRelation.relation_type == "owns",
        )
    )
    rows = result.scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_merge_entities_same_id_returns_422(client, auth_headers, entity_a):
    resp = await client.post(
        "/v1/entities/merge",
        json={"source_entity_id": str(entity_a.id), "target_entity_id": str(entity_a.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_merge_entities_source_not_found_returns_404(client, auth_headers, entity_a):
    resp = await client.post(
        "/v1/entities/merge",
        json={"source_entity_id": str(uuid.uuid4()), "target_entity_id": str(entity_a.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_merge_entities_target_not_found_returns_404(client, auth_headers, entity_a):
    resp = await client.post(
        "/v1/entities/merge",
        json={"source_entity_id": str(entity_a.id), "target_entity_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_merge_entity_with_zero_aliases(client, auth_headers, entity_b, entity_a):
    """Merge succeeds when source has zero aliases (empty alias set should not crash)."""
    # entity_b has no aliases by default
    resp = await client.post(
        "/v1/entities/merge",
        json={"source_entity_id": str(entity_b.id), "target_entity_id": str(entity_a.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["aliases_moved"] == 0


@pytest.mark.asyncio
async def test_merge_entity_with_zero_memory_links(client, auth_headers, entity_b, entity_a):
    """Merge succeeds when source has zero memory links (no MemoryEntityLink rows)."""
    # entity_b has no memory links by default
    resp = await client.post(
        "/v1/entities/merge",
        json={"source_entity_id": str(entity_b.id), "target_entity_id": str(entity_a.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["memory_links_moved"] == 0


@pytest.mark.asyncio
async def test_merge_entities_requires_auth(client, entity_a, entity_b):
    resp = await client.post(
        "/v1/entities/merge",
        json={"source_entity_id": str(entity_b.id), "target_entity_id": str(entity_a.id)},
    )
    assert resp.status_code == 401
