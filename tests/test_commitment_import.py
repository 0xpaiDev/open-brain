"""Tests for commitment plan import endpoint and multi-exercise routine endpoints.

Covers:
- Plan import dry_run / commit
- Idempotent re-import (same hash → same commitment_id)
- Rest-day rejection (no entry = 400)
- Per-exercise log, soft-delete, streak reconstruction
- Progression endpoint shape
- Legacy single-kind snapshot (backward compat)
"""

import hashlib
import json
import uuid
from datetime import date, timedelta

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_plan_payload(name="Stronglifts 5x5", days=2):
    """Build a minimal valid plan import payload."""
    today = date.today()
    schedule = [
        {
            "day": str(today),
            "rest": False,
            "exercises": [
                {"name": "Squat", "target": 5, "metric": "reps", "progression_metric": "kg"},
                {"name": "Bench Press", "target": 5, "metric": "reps", "progression_metric": "kg"},
            ],
        },
        {"day": str(today + timedelta(days=1)), "rest": True},
    ]
    if days > 2:
        for i in range(2, days):
            schedule.append(
                {
                    "day": str(today + timedelta(days=i)),
                    "rest": i % 2 == 1,
                    "exercises": [] if i % 2 == 1 else [
                        {"name": "Squat", "target": 5, "metric": "reps", "progression_metric": "kg"},
                    ],
                }
            )
    return {
        "name": name,
        "start_date": str(today),
        "end_date": str(today + timedelta(days=days - 1)),
        "schedule": schedule,
    }


async def _create_routine(client, headers, exercises=None, **overrides):
    """Helper to create a routine commitment."""
    today = date.today()
    if exercises is None:
        exercises = [
            {"name": "Push-ups", "target": 20, "metric": "reps", "progression_metric": "reps"},
            {"name": "Pull-ups", "target": 10, "metric": "reps", "progression_metric": "reps"},
            {"name": "Plank", "target": 60, "metric": "minutes", "progression_metric": "minutes"},
        ]
    payload = {
        "name": "Morning Routine",
        "kind": "routine",
        "exercises": exercises,
        "start_date": str(today),
        "end_date": str(today + timedelta(days=6)),
        **overrides,
    }
    return await client.post("/v1/commitments", json=payload, headers=headers)


# ── Legacy snapshot (backward compat) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_legacy_single_commitment_shape_unchanged(test_client, api_key_headers) -> None:
    """Existing single-kind CommitmentResponse shape is identical after migration."""
    today = date.today()
    resp = await test_client.post(
        "/v1/commitments",
        json={
            "name": "Push-ups challenge",
            "exercise": "push-ups",
            "daily_target": 50,
            "metric": "reps",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=6)),
        },
        headers=api_key_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    # Exact field check — backward compat snapshot
    assert body["exercise"] == "push-ups"
    assert body["daily_target"] == 50
    assert body["metric"] == "reps"
    assert body["kind"] == "single"
    assert body["status"] == "active"
    assert isinstance(body["entries"], list)
    assert len(body["entries"]) == 7
    assert body["exercises"] == []


# ── Routine create ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_routine_with_3_exercises(test_client, api_key_headers) -> None:
    """POST kind=routine creates commitment with 3 exercises and daily entries."""
    resp = await _create_routine(test_client, api_key_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "routine"
    assert len(body["exercises"]) == 3
    assert body["exercise"] is None
    assert body["daily_target"] == 0
    # 7 days pre-generated
    assert len(body["entries"]) == 7


@pytest.mark.asyncio
async def test_create_routine_max_5_exercises(test_client, api_key_headers) -> None:
    """POST kind=routine with exactly 5 exercises is accepted."""
    exercises = [
        {"name": f"Exercise {i}", "target": 10, "metric": "reps", "progression_metric": "reps"}
        for i in range(5)
    ]
    resp = await _create_routine(test_client, api_key_headers, exercises=exercises)
    assert resp.status_code == 201
    assert len(resp.json()["exercises"]) == 5


@pytest.mark.asyncio
async def test_create_routine_rejects_6_exercises(test_client, api_key_headers) -> None:
    """POST kind=routine with 6 exercises returns 422."""
    exercises = [
        {"name": f"Ex{i}", "target": 10, "metric": "reps", "progression_metric": "reps"}
        for i in range(6)
    ]
    resp = await _create_routine(test_client, api_key_headers, exercises=exercises)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_routine_rejects_0_exercises(test_client, api_key_headers) -> None:
    """POST kind=routine with 0 exercises returns 422."""
    resp = await _create_routine(test_client, api_key_headers, exercises=[])
    assert resp.status_code == 422


# ── Per-exercise log ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exercise_log_partial_does_not_advance_streak(test_client, api_key_headers) -> None:
    """Logging 2 of 3 exercises leaves entry status pending (streak does not advance)."""
    resp = await _create_routine(test_client, api_key_headers)
    assert resp.status_code == 201
    body = resp.json()
    commitment_id = body["id"]
    exercises = body["exercises"]
    assert len(exercises) == 3

    # Log first exercise
    log_resp = await test_client.post(
        f"/v1/commitments/{commitment_id}/exercises/{exercises[0]['id']}/log",
        json={"reps": 20},
        headers=api_key_headers,
    )
    assert log_resp.status_code == 201

    # Log second exercise
    log_resp2 = await test_client.post(
        f"/v1/commitments/{commitment_id}/exercises/{exercises[1]['id']}/log",
        json={"reps": 10},
        headers=api_key_headers,
    )
    assert log_resp2.status_code == 201

    # Check entry for today — still pending
    detail = await test_client.get(
        f"/v1/commitments/{commitment_id}", headers=api_key_headers
    )
    today_str = str(date.today())
    today_entry = next(
        (e for e in detail.json()["entries"] if e["entry_date"] == today_str), None
    )
    assert today_entry is not None
    assert today_entry["status"] == "pending"


@pytest.mark.asyncio
async def test_exercise_log_all_3_advances_streak(test_client, api_key_headers) -> None:
    """Logging all 3 exercises flips entry to hit (streak advances to 1)."""
    resp = await _create_routine(test_client, api_key_headers)
    assert resp.status_code == 201
    body = resp.json()
    commitment_id = body["id"]
    exercises = body["exercises"]

    # Log all 3 exercises
    for i, ex in enumerate(exercises):
        log_resp = await test_client.post(
            f"/v1/commitments/{commitment_id}/exercises/{ex['id']}/log",
            json={"reps": ex["target"]},
            headers=api_key_headers,
        )
        assert log_resp.status_code == 201

    # Check entry is hit now
    detail = await test_client.get(
        f"/v1/commitments/{commitment_id}", headers=api_key_headers
    )
    today_str = str(date.today())
    today_entry = next(
        (e for e in detail.json()["entries"] if e["entry_date"] == today_str), None
    )
    assert today_entry is not None
    assert today_entry["status"] == "hit"
    assert detail.json()["current_streak"] == 1


@pytest.mark.asyncio
async def test_exercise_log_out_of_order_still_advances(test_client, api_key_headers) -> None:
    """Logging exercises in reverse order still flips entry to hit."""
    resp = await _create_routine(test_client, api_key_headers)
    commitment_id = resp.json()["id"]
    exercises = resp.json()["exercises"]

    for ex in reversed(exercises):
        await test_client.post(
            f"/v1/commitments/{commitment_id}/exercises/{ex['id']}/log",
            json={"reps": ex["target"]},
            headers=api_key_headers,
        )

    detail = await test_client.get(
        f"/v1/commitments/{commitment_id}", headers=api_key_headers
    )
    today_str = str(date.today())
    today_entry = next(
        (e for e in detail.json()["entries"] if e["entry_date"] == today_str), None
    )
    assert today_entry["status"] == "hit"


# ── Soft-delete log ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_soft_delete_log_reverts_entry_to_pending(test_client, api_key_headers) -> None:
    """After logging all exercises and then deleting one log, entry reverts to pending."""
    resp = await _create_routine(test_client, api_key_headers)
    commitment_id = resp.json()["id"]
    exercises = resp.json()["exercises"]

    log_ids = []
    for ex in exercises:
        log_resp = await test_client.post(
            f"/v1/commitments/{commitment_id}/exercises/{ex['id']}/log",
            json={"reps": ex["target"]},
            headers=api_key_headers,
        )
        log_ids.append((ex["id"], log_resp.json()["id"]))

    # Delete one log
    ex_id, log_id = log_ids[0]
    del_resp = await test_client.delete(
        f"/v1/commitments/{commitment_id}/exercises/{ex_id}/logs/{log_id}",
        headers=api_key_headers,
    )
    assert del_resp.status_code == 204

    # Entry should be pending again
    detail = await test_client.get(
        f"/v1/commitments/{commitment_id}", headers=api_key_headers
    )
    today_str = str(date.today())
    today_entry = next(
        (e for e in detail.json()["entries"] if e["entry_date"] == today_str), None
    )
    assert today_entry["status"] == "pending"


@pytest.mark.asyncio
async def test_relog_after_delete_advances_streak(test_client, api_key_headers) -> None:
    """Deleting and re-logging an exercise still allows the day to complete."""
    resp = await _create_routine(test_client, api_key_headers)
    commitment_id = resp.json()["id"]
    exercises = resp.json()["exercises"]

    # Log all
    log_ids = []
    for ex in exercises:
        log_resp = await test_client.post(
            f"/v1/commitments/{commitment_id}/exercises/{ex['id']}/log",
            json={"reps": ex["target"]},
            headers=api_key_headers,
        )
        log_ids.append((ex["id"], log_resp.json()["id"]))

    # Delete first
    ex_id, log_id = log_ids[0]
    await test_client.delete(
        f"/v1/commitments/{commitment_id}/exercises/{ex_id}/logs/{log_id}",
        headers=api_key_headers,
    )

    # Re-log
    await test_client.post(
        f"/v1/commitments/{commitment_id}/exercises/{ex_id}/log",
        json={"reps": exercises[0]["target"]},
        headers=api_key_headers,
    )

    detail = await test_client.get(
        f"/v1/commitments/{commitment_id}", headers=api_key_headers
    )
    today_str = str(date.today())
    today_entry = next(
        (e for e in detail.json()["entries"] if e["entry_date"] == today_str), None
    )
    assert today_entry["status"] == "hit"


# ── Plan import ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_import_dry_run_zero_writes(test_client, api_key_headers) -> None:
    """Dry run returns preview with zero DB writes."""
    payload = _make_plan_payload()
    resp = await test_client.post(
        "/v1/commitments/import?dry_run=true",
        json=payload,
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert body["workout_days"] == 1
    assert body["rest_days"] == 1
    assert body["exercise_count"] == 2

    # DB should have no commitment rows
    list_resp = await test_client.get("/v1/commitments", headers=api_key_headers)
    assert list_resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_plan_import_commit_creates_rows(test_client, api_key_headers) -> None:
    """Commit creates commitment with exercises and workout-day entries only."""
    payload = _make_plan_payload()
    resp = await test_client.post(
        "/v1/commitments/import?dry_run=false",
        json=payload,
        headers=api_key_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["dry_run"] is False
    assert body["commitment_id"] is not None
    assert body["already_exists"] is False

    # Check commitment exists
    cid = body["commitment_id"]
    detail = await test_client.get(f"/v1/commitments/{cid}", headers=api_key_headers)
    assert detail.status_code == 200
    d = detail.json()
    assert d["kind"] == "plan"
    # Only 1 workout day entry (rest day has no entry)
    assert len(d["entries"]) == 1


@pytest.mark.asyncio
async def test_plan_import_rest_day_rejects_log(test_client, api_key_headers) -> None:
    """Logging on a rest day returns 400 (no entry for today if today is rest day)."""
    today = date.today()
    # Make today a rest day
    payload = {
        "name": "Rest Today Plan",
        "start_date": str(today),
        "end_date": str(today + timedelta(days=1)),
        "schedule": [
            {"day": str(today), "rest": True},
            {
                "day": str(today + timedelta(days=1)),
                "rest": False,
                "exercises": [
                    {"name": "Squat", "target": 5, "metric": "reps", "progression_metric": "kg"}
                ],
            },
        ],
    }
    import_resp = await test_client.post(
        "/v1/commitments/import?dry_run=false",
        json=payload,
        headers=api_key_headers,
    )
    assert import_resp.status_code == 201
    cid = import_resp.json()["commitment_id"]

    # Get exercise id
    detail = await test_client.get(f"/v1/commitments/{cid}", headers=api_key_headers)
    exercises = detail.json()["exercises"]
    assert len(exercises) == 1
    ex_id = exercises[0]["id"]

    # Try to log on today (rest day) — should 400
    log_resp = await test_client.post(
        f"/v1/commitments/{cid}/exercises/{ex_id}/log",
        json={"reps": 5},
        headers=api_key_headers,
    )
    assert log_resp.status_code == 400
    assert "rest" in log_resp.json()["detail"].lower() or "no entry" in log_resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_plan_import_idempotent_same_hash(test_client, api_key_headers) -> None:
    """Re-importing the same payload returns existing commitment_id, no new rows."""
    payload = _make_plan_payload(name="Idempotent Plan")

    resp1 = await test_client.post(
        "/v1/commitments/import?dry_run=false",
        json=payload,
        headers=api_key_headers,
    )
    assert resp1.status_code == 201
    cid1 = resp1.json()["commitment_id"]

    resp2 = await test_client.post(
        "/v1/commitments/import?dry_run=false",
        json=payload,
        headers=api_key_headers,
    )
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["commitment_id"] == cid1
    assert body2["already_exists"] is True


@pytest.mark.asyncio
async def test_plan_import_rejects_too_many_exercises(test_client, api_key_headers) -> None:
    """Import with >5 exercises on a workout day returns 422."""
    today = date.today()
    payload = {
        "name": "Too Many Exercises",
        "start_date": str(today),
        "end_date": str(today),
        "schedule": [
            {
                "day": str(today),
                "rest": False,
                "exercises": [
                    {"name": f"Ex{i}", "target": 5, "metric": "reps", "progression_metric": "reps"}
                    for i in range(6)
                ],
            }
        ],
    }
    resp = await test_client.post(
        "/v1/commitments/import?dry_run=true",
        json=payload,
        headers=api_key_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_plan_import_rejects_malformed_payload(test_client, api_key_headers) -> None:
    """Import with extra fields returns 422 (extra=forbid)."""
    payload = _make_plan_payload()
    payload["unknown_field"] = "bad"
    resp = await test_client.post(
        "/v1/commitments/import?dry_run=true",
        json=payload,
        headers=api_key_headers,
    )
    assert resp.status_code == 422


# ── PATCH plan rejects schedule edits ────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_plan_rejects_exercise_edits(test_client, api_key_headers) -> None:
    """PATCH on a plan commitment rejects changes other than status."""
    payload = _make_plan_payload(name="Uneditable Plan")
    import_resp = await test_client.post(
        "/v1/commitments/import?dry_run=false",
        json=payload,
        headers=api_key_headers,
    )
    assert import_resp.status_code == 201
    cid = import_resp.json()["commitment_id"]

    # Attempt to patch exercises (should be rejected)
    patch_resp = await test_client.patch(
        f"/v1/commitments/{cid}",
        json={"status": "abandoned", "exercises": []},
        headers=api_key_headers,
    )
    # extra=forbid on CommitmentUpdate should reject unknown fields
    assert patch_resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_plan_allows_abandon(test_client, api_key_headers) -> None:
    """PATCH status=abandoned is allowed on plan commitments."""
    payload = _make_plan_payload(name="Abandonable Plan")
    import_resp = await test_client.post(
        "/v1/commitments/import?dry_run=false",
        json=payload,
        headers=api_key_headers,
    )
    cid = import_resp.json()["commitment_id"]

    patch_resp = await test_client.patch(
        f"/v1/commitments/{cid}",
        json={"status": "abandoned"},
        headers=api_key_headers,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "abandoned"


# ── Progression endpoint ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_progression_empty_returns_correct_shape(test_client, api_key_headers) -> None:
    """Progression endpoint with 0 logs returns correct structure."""
    resp = await _create_routine(test_client, api_key_headers)
    cid = resp.json()["id"]

    prog_resp = await test_client.get(
        f"/v1/commitments/{cid}/progression", headers=api_key_headers
    )
    assert prog_resp.status_code == 200
    body = prog_resp.json()
    assert isinstance(body, list)
    assert len(body) == 3  # 3 exercises, each with empty points
    for item in body:
        assert "exercise_id" in item
        assert "exercise_name" in item
        assert "points" in item
        assert item["points"] == []


@pytest.mark.asyncio
async def test_progression_1_log_returns_single_point(test_client, api_key_headers) -> None:
    """Progression endpoint with 1 log returns 1 point for that exercise."""
    resp = await _create_routine(test_client, api_key_headers)
    cid = resp.json()["id"]
    exercises = resp.json()["exercises"]
    ex = exercises[0]

    await test_client.post(
        f"/v1/commitments/{cid}/exercises/{ex['id']}/log",
        json={"reps": 20},
        headers=api_key_headers,
    )

    prog_resp = await test_client.get(
        f"/v1/commitments/{cid}/progression", headers=api_key_headers
    )
    assert prog_resp.status_code == 200
    body = prog_resp.json()
    first = next(item for item in body if item["exercise_id"] == ex["id"])
    assert len(first["points"]) == 1
    assert first["points"][0]["date"] == str(date.today())


# ── Single-kind log still works ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_kind_log_endpoint_unchanged(test_client, api_key_headers) -> None:
    """POST /v1/commitments/{id}/log still works for kind=single commitments."""
    today = date.today()
    resp = await test_client.post(
        "/v1/commitments",
        json={
            "name": "Push-ups",
            "exercise": "push-ups",
            "daily_target": 20,
            "metric": "reps",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=6)),
        },
        headers=api_key_headers,
    )
    assert resp.status_code == 201
    cid = resp.json()["id"]

    log_resp = await test_client.post(
        f"/v1/commitments/{cid}/log",
        json={"count": 20},
        headers=api_key_headers,
    )
    assert log_resp.status_code == 200
    assert log_resp.json()["status"] == "hit"


@pytest.mark.asyncio
async def test_routine_kind_rejects_single_log_endpoint(test_client, api_key_headers) -> None:
    """POST /v1/commitments/{id}/log returns 400 for routine kind."""
    resp = await _create_routine(test_client, api_key_headers)
    cid = resp.json()["id"]

    log_resp = await test_client.post(
        f"/v1/commitments/{cid}/log",
        json={"count": 10},
        headers=api_key_headers,
    )
    assert log_resp.status_code == 400
