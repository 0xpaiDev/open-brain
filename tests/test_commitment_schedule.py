"""Tests for schedule service: GET /schedule, day-swap PATCH endpoint."""

from datetime import date, timedelta

import pytest

from tests.test_commitment_import import _make_plan_payload


def _make_resolved_payload(name="Test Plan", days=4):
    payload = _make_plan_payload(name=name, days=days)
    payload["resolved_exercises"] = [
        {"name": "Squat", "display_name": "Squat", "target": 5, "metric": "reps", "progression_metric": "kg"},
        {"name": "Bench Press", "display_name": "Bench Press", "target": 5, "metric": "reps", "progression_metric": "kg"},
    ]
    return payload


@pytest.mark.asyncio
async def test_get_schedule_returns_all_days(test_client, api_key_headers):
    """GET /schedule returns every day from start to end, including rest days."""
    today = date.today()
    payload = _make_resolved_payload(days=4)
    create_resp = await test_client.post(
        "/v1/commitments/import?dry_run=false", json=payload, headers=api_key_headers
    )
    assert create_resp.status_code == 201
    commitment_id = create_resp.json()["commitment_id"]

    resp = await test_client.get(
        f"/v1/commitments/{commitment_id}/schedule", headers=api_key_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["commitment_id"] == commitment_id
    assert len(data["days"]) == 4  # 4 days total
    statuses = {d["date"]: d["status"] for d in data["days"]}
    assert statuses[str(today)] in ("pending", "hit", "miss")  # workout day
    assert statuses[str(today + timedelta(days=1))] == "rest"   # rest day


@pytest.mark.asyncio
async def test_get_schedule_includes_exercises_per_day(test_client, api_key_headers):
    """Workout days in schedule include their assigned exercises."""
    today = date.today()
    payload = _make_resolved_payload(days=2)
    create_resp = await test_client.post(
        "/v1/commitments/import?dry_run=false", json=payload, headers=api_key_headers
    )
    assert create_resp.status_code == 201
    commitment_id = create_resp.json()["commitment_id"]

    resp = await test_client.get(
        f"/v1/commitments/{commitment_id}/schedule", headers=api_key_headers
    )
    days = resp.json()["days"]
    workout_day = next(d for d in days if d["status"] != "rest")
    assert len(workout_day["exercises"]) == 2
    names = {e["name"] for e in workout_day["exercises"]}
    assert "Squat" in names


@pytest.mark.asyncio
async def test_swap_rest_to_workout(test_client, api_key_headers):
    """PATCH entries/{date} to_workout creates entry + entry_exercises."""
    today = date.today()
    payload = _make_resolved_payload(days=2)
    create_resp = await test_client.post(
        "/v1/commitments/import?dry_run=false", json=payload, headers=api_key_headers
    )
    assert create_resp.status_code == 201
    commitment_id = create_resp.json()["commitment_id"]

    # Get exercise IDs from the commitment
    detail = await test_client.get(f"/v1/commitments/{commitment_id}", headers=api_key_headers)
    exercise_ids = [e["id"] for e in detail.json()["exercises"]]

    rest_day = str(today + timedelta(days=1))
    resp = await test_client.patch(
        f"/v1/commitments/{commitment_id}/entries/{rest_day}",
        json={"action": "to_workout", "exercise_ids": exercise_ids},
        headers=api_key_headers,
    )
    assert resp.status_code == 200

    # Schedule should now show workout day
    schedule = await test_client.get(
        f"/v1/commitments/{commitment_id}/schedule", headers=api_key_headers
    )
    days = {d["date"]: d for d in schedule.json()["days"]}
    assert days[rest_day]["status"] == "pending"
    assert len(days[rest_day]["exercises"]) == len(exercise_ids)


@pytest.mark.asyncio
async def test_swap_workout_to_rest_pending(test_client, api_key_headers):
    """PATCH entries/{date} to_rest on pending entry deletes it."""
    today = date.today()
    payload = _make_resolved_payload(days=2)
    create_resp = await test_client.post(
        "/v1/commitments/import?dry_run=false", json=payload, headers=api_key_headers
    )
    assert create_resp.status_code == 201
    commitment_id = create_resp.json()["commitment_id"]

    resp = await test_client.patch(
        f"/v1/commitments/{commitment_id}/entries/{str(today)}",
        json={"action": "to_rest", "exercise_ids": []},
        headers=api_key_headers,
    )
    assert resp.status_code == 200

    schedule = await test_client.get(
        f"/v1/commitments/{commitment_id}/schedule", headers=api_key_headers
    )
    days = {d["date"]: d for d in schedule.json()["days"]}
    assert days[str(today)]["status"] == "rest"


@pytest.mark.asyncio
async def test_swap_workout_to_rest_hit_rejected(test_client, api_key_headers, async_session):
    """PATCH to_rest on a hit entry returns 400."""
    from sqlalchemy import select as sa_select, and_
    from src.core.models import CommitmentEntry

    today = date.today()
    payload = _make_resolved_payload(days=2)
    create_resp = await test_client.post(
        "/v1/commitments/import?dry_run=false", json=payload, headers=api_key_headers
    )
    assert create_resp.status_code == 201
    commitment_id = create_resp.json()["commitment_id"]

    # Manually mark today's entry as hit
    async_session.expire_all()
    result = await async_session.execute(
        sa_select(CommitmentEntry).where(
            and_(CommitmentEntry.commitment_id == commitment_id, CommitmentEntry.entry_date == today)
        )
    )
    entry = result.scalar_one()
    entry.status = "hit"
    await async_session.commit()

    resp = await test_client.patch(
        f"/v1/commitments/{commitment_id}/entries/{str(today)}",
        json={"action": "to_rest", "exercise_ids": []},
        headers=api_key_headers,
    )
    assert resp.status_code == 400
