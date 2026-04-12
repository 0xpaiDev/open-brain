"""Tests for the Commitments API endpoints.

Covers CRUD, log, validation, streak logic, and miss detection.
"""

import uuid
from datetime import UTC, date, timedelta

import pytest

# ── Helpers ────────────────────────────────────────────────────────────────────


async def _create_commitment(client, headers, **overrides):
    """Helper to create a commitment with sensible defaults."""
    today = date.today()
    payload = {
        "name": "Push-ups challenge",
        "exercise": "push-ups",
        "daily_target": 50,
        "metric": "reps",
        "start_date": str(today),
        "end_date": str(today + timedelta(days=29)),
        **overrides,
    }
    resp = await client.post("/v1/commitments", json=payload, headers=headers)
    return resp


# ── POST /v1/commitments ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_commitment(test_client, api_key_headers) -> None:
    """POST creates commitment + generates entries for each day."""
    today = date.today()
    end = today + timedelta(days=6)
    resp = await _create_commitment(
        test_client, api_key_headers, start_date=str(today), end_date=str(end)
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Push-ups challenge"
    assert body["exercise"] == "push-ups"
    assert body["daily_target"] == 50
    assert body["metric"] == "reps"
    assert body["status"] == "active"
    assert len(body["entries"]) == 7


@pytest.mark.asyncio
async def test_create_commitment_single_day(test_client, api_key_headers) -> None:
    """POST with same start and end date creates 1 entry."""
    today = date.today()
    resp = await _create_commitment(
        test_client, api_key_headers, start_date=str(today), end_date=str(today)
    )
    assert resp.status_code == 201
    assert len(resp.json()["entries"]) == 1


@pytest.mark.asyncio
async def test_create_commitment_end_before_start(test_client, api_key_headers) -> None:
    """POST with end_date before start_date returns 422."""
    today = date.today()
    resp = await _create_commitment(
        test_client,
        api_key_headers,
        start_date=str(today),
        end_date=str(today - timedelta(days=1)),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_commitment_negative_target(test_client, api_key_headers) -> None:
    """POST with daily_target <= 0 returns 422."""
    resp = await _create_commitment(test_client, api_key_headers, daily_target=0)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_commitment_invalid_metric(test_client, api_key_headers) -> None:
    """POST with invalid metric returns 422."""
    resp = await _create_commitment(test_client, api_key_headers, metric="calories")
    assert resp.status_code == 422


# ── GET /v1/commitments ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_commitments_empty(test_client, api_key_headers) -> None:
    """GET with no commitments returns empty list."""
    resp = await test_client.get("/v1/commitments", headers=api_key_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
    assert resp.json()["commitments"] == []


@pytest.mark.asyncio
async def test_list_commitments_active_filter(test_client, api_key_headers) -> None:
    """GET defaults to active filter."""
    await _create_commitment(test_client, api_key_headers)
    resp = await test_client.get("/v1/commitments", headers=api_key_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_list_commitments_all_filter(test_client, api_key_headers) -> None:
    """GET ?status=all includes abandoned commitments."""
    create_resp = await _create_commitment(test_client, api_key_headers)
    cid = create_resp.json()["id"]
    await test_client.patch(
        f"/v1/commitments/{cid}", json={"status": "abandoned"}, headers=api_key_headers
    )

    active = await test_client.get("/v1/commitments?status=active", headers=api_key_headers)
    assert active.json()["total"] == 0

    all_resp = await test_client.get("/v1/commitments?status=all", headers=api_key_headers)
    assert all_resp.json()["total"] == 1


# ── GET /v1/commitments/{id} ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_commitment(test_client, api_key_headers) -> None:
    """GET returns commitment with entries."""
    create_resp = await _create_commitment(test_client, api_key_headers)
    cid = create_resp.json()["id"]

    resp = await test_client.get(f"/v1/commitments/{cid}", headers=api_key_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == cid
    assert len(resp.json()["entries"]) > 0


@pytest.mark.asyncio
async def test_get_commitment_not_found(test_client, api_key_headers) -> None:
    """GET with fake ID returns 404."""
    resp = await test_client.get(
        f"/v1/commitments/{uuid.uuid4()}", headers=api_key_headers
    )
    assert resp.status_code == 404


# ── PATCH /v1/commitments/{id} ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_abandon_commitment(test_client, api_key_headers) -> None:
    """PATCH to abandoned removes from active list."""
    create_resp = await _create_commitment(test_client, api_key_headers)
    cid = create_resp.json()["id"]

    resp = await test_client.patch(
        f"/v1/commitments/{cid}", json={"status": "abandoned"}, headers=api_key_headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "abandoned"


# ── POST /v1/commitments/{id}/log ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_count(test_client, api_key_headers) -> None:
    """POST /log increments logged_count."""
    today = date.today()
    create_resp = await _create_commitment(
        test_client, api_key_headers, start_date=str(today), end_date=str(today + timedelta(days=2))
    )
    cid = create_resp.json()["id"]

    resp = await test_client.post(
        f"/v1/commitments/{cid}/log", json={"count": 10}, headers=api_key_headers
    )
    assert resp.status_code == 200
    assert resp.json()["logged_count"] == 10
    assert resp.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_log_count_hits_target(test_client, api_key_headers) -> None:
    """Logging enough transitions status to hit."""
    today = date.today()
    create_resp = await _create_commitment(
        test_client, api_key_headers,
        daily_target=20,
        start_date=str(today),
        end_date=str(today + timedelta(days=2)),
    )
    cid = create_resp.json()["id"]

    await test_client.post(
        f"/v1/commitments/{cid}/log", json={"count": 10}, headers=api_key_headers
    )
    resp = await test_client.post(
        f"/v1/commitments/{cid}/log", json={"count": 10}, headers=api_key_headers
    )
    assert resp.status_code == 200
    assert resp.json()["logged_count"] == 20
    assert resp.json()["status"] == "hit"


@pytest.mark.asyncio
async def test_log_count_already_hit(test_client, api_key_headers) -> None:
    """Logging more after hit still increments (no cap)."""
    today = date.today()
    create_resp = await _create_commitment(
        test_client, api_key_headers,
        daily_target=5,
        start_date=str(today),
        end_date=str(today + timedelta(days=2)),
    )
    cid = create_resp.json()["id"]

    await test_client.post(
        f"/v1/commitments/{cid}/log", json={"count": 10}, headers=api_key_headers
    )
    resp = await test_client.post(
        f"/v1/commitments/{cid}/log", json={"count": 5}, headers=api_key_headers
    )
    assert resp.status_code == 200
    assert resp.json()["logged_count"] == 15
    assert resp.json()["status"] == "hit"


@pytest.mark.asyncio
async def test_log_count_not_found(test_client, api_key_headers) -> None:
    """POST /log with fake ID returns 404."""
    resp = await test_client.post(
        f"/v1/commitments/{uuid.uuid4()}/log", json={"count": 5}, headers=api_key_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_log_count_abandoned(test_client, api_key_headers) -> None:
    """Cannot log on an abandoned commitment."""
    today = date.today()
    create_resp = await _create_commitment(
        test_client, api_key_headers,
        start_date=str(today),
        end_date=str(today + timedelta(days=2)),
    )
    cid = create_resp.json()["id"]

    await test_client.patch(
        f"/v1/commitments/{cid}", json={"status": "abandoned"}, headers=api_key_headers
    )
    resp = await test_client.post(
        f"/v1/commitments/{cid}/log", json={"count": 5}, headers=api_key_headers
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_log_count_future_entry(test_client, api_key_headers) -> None:
    """Cannot log if commitment hasn't started yet (no entry for today)."""
    future = date.today() + timedelta(days=10)
    create_resp = await _create_commitment(
        test_client, api_key_headers,
        start_date=str(future),
        end_date=str(future + timedelta(days=5)),
    )
    cid = create_resp.json()["id"]

    resp = await test_client.post(
        f"/v1/commitments/{cid}/log", json={"count": 5}, headers=api_key_headers
    )
    assert resp.status_code == 400


# ── Model tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_commitment_model_defaults(async_session) -> None:
    """Commitment model has correct defaults."""
    from src.core.models import Commitment

    c = Commitment(
        name="Test",
        exercise="test",
        daily_target=10,
        start_date=date.today(),
        end_date=date.today() + timedelta(days=5),
    )
    async_session.add(c)
    await async_session.commit()
    await async_session.refresh(c)

    assert c.metric == "reps"
    assert c.status == "active"
    assert c.id is not None


@pytest.mark.asyncio
async def test_commitment_entry_unique_constraint(async_session) -> None:
    """CommitmentEntry enforces unique(commitment_id, entry_date)."""
    from sqlalchemy.exc import IntegrityError

    from src.core.models import Commitment, CommitmentEntry

    c = Commitment(
        name="Test", exercise="test", daily_target=10,
        start_date=date.today(), end_date=date.today(),
    )
    async_session.add(c)
    await async_session.flush()

    e1 = CommitmentEntry(commitment_id=c.id, entry_date=date.today())
    async_session.add(e1)
    await async_session.flush()

    e2 = CommitmentEntry(commitment_id=c.id, entry_date=date.today())
    async_session.add(e2)
    with pytest.raises(IntegrityError):
        await async_session.flush()


@pytest.mark.asyncio
async def test_strava_activity_model(async_session) -> None:
    """StravaActivity model stores and retrieves data."""
    from datetime import datetime

    from src.core.models import StravaActivity

    a = StravaActivity(
        strava_id=12345678,
        activity_type="Ride",
        name="Morning Ride",
        distance_m=50000.0,
        duration_s=7200,
        started_at=datetime.now(UTC),
    )
    async_session.add(a)
    await async_session.commit()
    await async_session.refresh(a)

    assert a.strava_id == 12345678
    assert a.activity_type == "Ride"


@pytest.mark.asyncio
async def test_memory_item_tags_default(async_session) -> None:
    """New memory_items have tags=[] by default."""
    from src.core.models import MemoryItem, RawMemory

    raw = RawMemory(source="test", raw_text="test content")
    async_session.add(raw)
    await async_session.flush()

    mi = MemoryItem(raw_id=raw.id, content="test", type="memory")
    async_session.add(mi)
    await async_session.commit()
    await async_session.refresh(mi)

    assert mi.tags == []


@pytest.mark.asyncio
async def test_memory_item_tags_set(async_session) -> None:
    """Can set tags array on MemoryItem creation."""
    from src.core.models import MemoryItem, RawMemory

    raw = RawMemory(source="test", raw_text="test content")
    async_session.add(raw)
    await async_session.flush()

    mi = MemoryItem(
        raw_id=raw.id, content="test", type="memory",
        tags=["training:strava", "training:weekly"],
    )
    async_session.add(mi)
    await async_session.commit()
    await async_session.refresh(mi)

    assert mi.tags == ["training:strava", "training:weekly"]


# ── Pulse nutrition extension ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pulse_update_with_nutrition(test_client, api_key_headers) -> None:
    """PATCH /v1/pulse/today with clean_meal + alcohol updates correctly."""
    # Create a pulse first
    await test_client.post("/v1/pulse/start", headers=api_key_headers)

    resp = await test_client.patch(
        "/v1/pulse/today",
        json={"clean_meal": True, "alcohol": False, "status": "completed"},
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["clean_meal"] is True
    assert body["alcohol"] is False


@pytest.mark.asyncio
async def test_pulse_nutrition_fields_optional(test_client, api_key_headers) -> None:
    """PATCH without nutrition fields leaves them null."""
    await test_client.post("/v1/pulse/start", headers=api_key_headers)

    resp = await test_client.patch(
        "/v1/pulse/today",
        json={"status": "completed"},
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["clean_meal"] is None
    assert body["alcohol"] is None


# ── Pulse sync includes nutrition ──────────────────────────────────────────────


def test_pulse_sync_format_includes_nutrition() -> None:
    """_format_pulse_content includes clean_meal and alcohol when set."""
    from datetime import datetime
    from unittest.mock import MagicMock

    from src.pipeline.pulse_sync import _format_pulse_content

    pulse = MagicMock()
    pulse.pulse_date = datetime(2026, 4, 12, tzinfo=UTC)
    pulse.sleep_quality = 4
    pulse.energy_level = 3
    pulse.wake_time = "07:00"
    pulse.notes = None
    pulse.ai_question = None
    pulse.ai_question_response = None
    pulse.clean_meal = True
    pulse.alcohol = False

    content = _format_pulse_content(pulse)
    assert "Clean eating: yes" in content
    assert "Alcohol: no" in content


def test_pulse_sync_format_skips_null_nutrition() -> None:
    """_format_pulse_content skips nutrition when null."""
    from datetime import datetime
    from unittest.mock import MagicMock

    from src.pipeline.pulse_sync import _format_pulse_content

    pulse = MagicMock()
    pulse.pulse_date = datetime(2026, 4, 12, tzinfo=UTC)
    pulse.sleep_quality = 4
    pulse.energy_level = None
    pulse.wake_time = None
    pulse.notes = None
    pulse.ai_question = None
    pulse.ai_question_response = None
    pulse.clean_meal = None
    pulse.alcohol = None

    content = _format_pulse_content(pulse)
    assert "Clean eating" not in content
    assert "Alcohol" not in content
