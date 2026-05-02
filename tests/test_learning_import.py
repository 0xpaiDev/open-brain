"""Tests for Learning Library V2: bulk import and rate limiting.

10 tests covering the import endpoint and its invariants.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from src.api.middleware.rate_limit import limiter
from src.core.models import LearningMaterial, LearningTopic

# ── Local helpers (mirror test_learning.py) ───────────────────────────────────


async def _mk_topic(session, name="Topic A", active=True, position=0):
    from src.core.models import LearningTopic

    t = LearningTopic(name=name, is_active=active, position=position)
    session.add(t)
    await session.commit()
    await session.refresh(t)
    return t


# ── Rate limit fixture ────────────────────────────────────────────────────────


@pytest.fixture()
def reset_limiter_storage():
    """Re-enable and clean the in-memory limiter for rate-limit tests.

    The global set_test_env fixture disables the limiter. This fixture opts
    back in and resets storage so the test starts with a clean slate.
    """
    limiter.enabled = True
    limiter._limiter.storage.reset()
    yield
    limiter._limiter.storage.reset()
    limiter.enabled = False


# ── Import tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_import_dry_run_writes_nothing(test_client, api_key_headers, async_session):
    """dry_run=true returns counts but writes zero rows."""
    payload = {
        "topics": [
            {
                "name": "DryRunTopic",
                "sections": [
                    {"name": "S1", "items": [{"title": "I1"}, {"title": "I2"}]},
                ],
                "material": {"content": "# Dry run source"},
            }
        ]
    }
    resp = await test_client.post(
        "/v1/learning/import?dry_run=true", json=payload, headers=api_key_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["dry_run"] is True
    assert data["topics_created"] == 1
    assert data["sections_created"] == 1
    assert data["items_created"] == 2
    assert data["materials_created"] == 1
    assert data["created_topic_ids"] == []

    count = await async_session.scalar(select(func.count()).select_from(LearningTopic))
    assert count == 0


@pytest.mark.asyncio
async def test_import_commits_full_tree(test_client, api_key_headers, async_session):
    """dry_run=false persists the full topic+sections+items+material tree."""
    payload = {
        "topics": [
            {
                "name": "CommitTopic",
                "sections": [
                    {"name": "S1", "items": [{"title": "I1"}, {"title": "I2"}, {"title": "I3"}]},
                    {"name": "S2", "items": [{"title": "I4"}, {"title": "I5"}, {"title": "I6"}]},
                ],
                "material": {"content": "# Source material", "source_type": "article"},
            }
        ]
    }
    resp = await test_client.post(
        "/v1/learning/import?dry_run=false", json=payload, headers=api_key_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["dry_run"] is False
    assert data["topics_created"] == 1
    assert data["sections_created"] == 2
    assert data["items_created"] == 6
    assert data["materials_created"] == 1
    assert len(data["created_topic_ids"]) == 1

    topic_count = await async_session.scalar(select(func.count()).select_from(LearningTopic))
    assert topic_count == 1

    mat_count = await async_session.scalar(select(func.count()).select_from(LearningMaterial))
    assert mat_count == 1


@pytest.mark.asyncio
async def test_import_skips_name_collision(test_client, api_key_headers, async_session):
    """Topics with colliding names are skipped; non-colliding ones are created."""
    await _mk_topic(async_session, name="Existing")

    payload = {
        "topics": [
            {"name": "Existing", "sections": []},
            {"name": "New", "sections": []},
        ]
    }
    resp = await test_client.post(
        "/v1/learning/import?dry_run=false", json=payload, headers=api_key_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["topics_created"] == 1
    assert len(data["topics_skipped"]) == 1
    assert data["topics_skipped"][0]["name"] == "Existing"
    assert data["topics_skipped"][0]["reason"] == "name_collision"

    count = await async_session.scalar(select(func.count()).select_from(LearningTopic))
    assert count == 2  # pre-existing + "New"


@pytest.mark.asyncio
async def test_import_skip_is_case_insensitive(test_client, api_key_headers, async_session):
    """Name collision check is case-insensitive."""
    await _mk_topic(async_session, name="Pgvector")

    payload = {"topics": [{"name": "pgvector", "sections": []}]}
    resp = await test_client.post(
        "/v1/learning/import?dry_run=false", json=payload, headers=api_key_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["topics_created"] == 0
    assert len(data["topics_skipped"]) == 1

    count = await async_session.scalar(select(func.count()).select_from(LearningTopic))
    assert count == 1  # only the pre-existing one


@pytest.mark.asyncio
async def test_import_material_optional(test_client, api_key_headers, async_session):
    """Topics without material import cleanly; materials_created=0."""
    payload = {"topics": [{"name": "NoMaterial", "sections": []}]}
    resp = await test_client.post(
        "/v1/learning/import?dry_run=false", json=payload, headers=api_key_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["materials_created"] == 0
    assert len(data["created_topic_ids"]) == 1

    mat_count = await async_session.scalar(select(func.count()).select_from(LearningMaterial))
    assert mat_count == 0

    topic_id = data["created_topic_ids"][0]
    mat_resp = await test_client.get(
        f"/v1/learning/topics/{topic_id}/material", headers=api_key_headers
    )
    assert mat_resp.status_code == 200
    assert mat_resp.json() is None


@pytest.mark.asyncio
async def test_import_rejects_malformed_json(test_client, api_key_headers):
    """Missing required 'name' field returns 422 Unprocessable Entity."""
    payload = {"topics": [{"sections": []}]}  # missing name
    resp = await test_client.post(
        "/v1/learning/import?dry_run=false", json=payload, headers=api_key_headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_import_rejects_position_field(test_client, api_key_headers):
    """extra='forbid' means any 'position' field in payload returns 422."""
    payload = {"topics": [{"name": "T", "position": 0, "sections": []}]}
    resp = await test_client.post(
        "/v1/learning/import?dry_run=false", json=payload, headers=api_key_headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_import_rejects_empty_topics_list(test_client, api_key_headers):
    """topics: [] fails Pydantic min_length=1 validation."""
    payload = {"topics": []}
    resp = await test_client.post(
        "/v1/learning/import?dry_run=false", json=payload, headers=api_key_headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_import_atomicity_rolls_back_on_db_error(
    test_client, api_key_headers, async_session, monkeypatch
):
    """If commit raises, all adds are rolled back — zero rows persist."""
    original_commit = async_session.commit

    async def _raise_on_commit():
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(async_session, "commit", _raise_on_commit)

    resp = await test_client.post(
        "/v1/learning/import?dry_run=false",
        json={"topics": [{"name": "AtomicTest", "sections": []}]},
        headers=api_key_headers,
    )
    assert resp.status_code == 500

    # Restore commit so we can query the DB
    async_session.commit = original_commit
    count = await async_session.scalar(select(func.count()).select_from(LearningTopic))
    assert count == 0


@pytest.mark.asyncio
async def test_import_assigns_positions_in_array_order(
    test_client, api_key_headers, async_session
):
    """Topics (and sections/items) get position = array index."""
    from src.core.models import LearningSection

    payload = {
        "topics": [
            {
                "name": "TopicFirst",
                "sections": [
                    {"name": "S0", "items": []},
                    {"name": "S1", "items": []},
                    {"name": "S2", "items": []},
                ],
            }
        ]
    }
    resp = await test_client.post(
        "/v1/learning/import?dry_run=false", json=payload, headers=api_key_headers
    )
    assert resp.status_code == 200

    topic_result = await async_session.execute(
        select(LearningTopic).where(LearningTopic.name == "TopicFirst")
    )
    topic = topic_result.scalar_one()
    assert topic.position == 0

    sections_result = await async_session.execute(
        select(LearningSection)
        .where(LearningSection.topic_id == topic.id)
        .order_by(LearningSection.position)
    )
    sections = list(sections_result.scalars().all())
    assert [s.position for s in sections] == [0, 1, 2]


@pytest.mark.asyncio
async def test_import_rate_limit_5_per_minute(
    test_client, api_key_headers, reset_limiter_storage
):
    """POST /v1/learning/import enforces 5/minute; 6th request returns 429."""
    for i in range(5):
        r = await test_client.post(
            "/v1/learning/import?dry_run=false",
            json={"topics": [{"name": f"RateTest{i}", "sections": []}]},
            headers=api_key_headers,
        )
        assert r.status_code == 200, f"Request {i + 1} failed with {r.status_code}"

    r6 = await test_client.post(
        "/v1/learning/import?dry_run=false",
        json={"topics": [{"name": "RateTestFinal", "sections": []}]},
        headers=api_key_headers,
    )
    assert r6.status_code == 429
