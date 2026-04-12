"""Strava webhook and activity endpoints.

GET    /v1/strava/webhook      — webhook verification (PUBLIC)
POST   /v1/strava/webhook      — webhook event receiver (PUBLIC, HMAC verified)
GET    /v1/strava/activities    — list cached activities (API key auth)
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import limiter, strava_limit
from src.core.database import get_db
from src.core.models import StravaActivity

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Pydantic models ────────────────────────────────────────────────────────────


class StravaWebhookEvent(BaseModel):
    aspect_type: str  # "create" | "update" | "delete"
    object_type: str  # "activity" | "athlete"
    object_id: int
    owner_id: int
    subscription_id: int | None = None
    event_time: int | None = None
    updates: dict | None = None


class ActivityResponse(BaseModel):
    id: str
    strava_id: int
    activity_type: str | None
    name: str | None
    distance_m: float | None
    duration_s: int | None
    tss: float | None
    avg_power_w: float | None
    avg_hr: int | None
    elevation_m: float | None
    started_at: str
    created_at: str


class ActivityListResponse(BaseModel):
    activities: list[ActivityResponse]
    total: int


# ── Helpers ────────────────────────────────────────────────────────────────────


def _get_settings():
    from src.core import config

    if config.settings is None:
        config.settings = config.Settings()
    return config.settings


def _verify_hmac(body: bytes, signature: str, secret: str) -> bool:
    """Verify Strava webhook HMAC-SHA256 signature."""
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _activity_to_response(activity: StravaActivity) -> ActivityResponse:
    return ActivityResponse(
        id=str(activity.id),
        strava_id=activity.strava_id,
        activity_type=activity.activity_type,
        name=activity.name,
        distance_m=activity.distance_m,
        duration_s=activity.duration_s,
        tss=activity.tss,
        avg_power_w=activity.avg_power_w,
        avg_hr=activity.avg_hr,
        elevation_m=activity.elevation_m,
        started_at=str(activity.started_at),
        created_at=str(activity.created_at),
    )


async def _fetch_and_upsert_activity(
    session: AsyncSession, activity_id: int
) -> StravaActivity | None:
    """Fetch activity details from Strava API and upsert into database."""
    settings = _get_settings()
    access_token = settings.strava_access_token.get_secret_value()
    if not access_token:
        logger.warning("strava_no_access_token")
        return None

    try:
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://www.strava.com/api/v3/activities/{activity_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10.0,
            )
            if resp.status_code != 200:
                logger.warning(
                    "strava_fetch_failed",
                    activity_id=activity_id,
                    status=resp.status_code,
                )
                return None
            data = resp.json()
    except Exception:
        logger.warning("strava_fetch_error", activity_id=activity_id, exc_info=True)
        return None

    # Check for existing activity (upsert)
    result = await session.execute(
        select(StravaActivity).where(StravaActivity.strava_id == activity_id)
    )
    existing = result.scalar_one_or_none()

    started = datetime.fromisoformat(data.get("start_date", "").replace("Z", "+00:00"))

    if existing:
        existing.activity_type = data.get("type")
        existing.name = data.get("name")
        existing.distance_m = data.get("distance")
        existing.duration_s = data.get("moving_time")
        existing.avg_power_w = data.get("average_watts")
        existing.avg_hr = data.get("average_heartrate")
        existing.elevation_m = data.get("total_elevation_gain")
        existing.started_at = started
        existing.raw_data = data
        activity = existing
    else:
        activity = StravaActivity(
            strava_id=activity_id,
            activity_type=data.get("type"),
            name=data.get("name"),
            distance_m=data.get("distance"),
            duration_s=data.get("moving_time"),
            avg_power_w=data.get("average_watts"),
            avg_hr=data.get("average_heartrate"),
            elevation_m=data.get("total_elevation_gain"),
            started_at=started,
            raw_data=data,
        )
        session.add(activity)

    await session.commit()
    await session.refresh(activity)

    logger.info(
        "strava_activity_upserted",
        strava_id=activity_id,
        type=activity.activity_type,
        name=activity.name,
    )
    return activity


# ── GET /v1/strava/webhook (verification) ─────────────────────────────────────


@router.get("/v1/strava/webhook")
@limiter.limit(strava_limit)
async def verify_strava_webhook(
    request: Request,
) -> dict:
    """Strava webhook subscription verification.

    Strava sends hub.mode, hub.challenge, hub.verify_token as query params.
    Respond with {"hub.challenge": <challenge>} if verify_token matches.
    """
    mode = request.query_params.get("hub.mode")
    challenge = request.query_params.get("hub.challenge")
    verify_token = request.query_params.get("hub.verify_token")

    settings = _get_settings()
    if mode == "subscribe" and hmac.compare_digest(
        verify_token or "", settings.strava_verify_token
    ):
        logger.info("strava_webhook_verified")
        return {"hub.challenge": challenge}

    raise HTTPException(status_code=403, detail="Verification failed")


# ── POST /v1/strava/webhook (event receiver) ──────────────────────────────────


@router.post("/v1/strava/webhook", status_code=status.HTTP_200_OK)
@limiter.limit(strava_limit)
async def receive_strava_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Receive Strava webhook events. Validates HMAC signature.

    On activity create/update: fetch full details and upsert.
    On activity delete: remove from cache.
    """
    body = await request.body()

    # Verify HMAC signature using client secret
    settings = _get_settings()
    client_secret = settings.strava_client_secret.get_secret_value()
    if client_secret:
        signature = request.headers.get("X-Hub-Signature", "")
        # Strava sends signature as "sha256=<hex>"
        if signature.startswith("sha256="):
            signature = signature[7:]
        if not _verify_hmac(body, signature, client_secret):
            raise HTTPException(status_code=403, detail="Invalid signature")

    import json

    try:
        event_data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    event = StravaWebhookEvent(**event_data)

    if event.object_type != "activity":
        return {"status": "ignored"}

    if event.aspect_type in ("create", "update"):
        await _fetch_and_upsert_activity(session, event.object_id)
    elif event.aspect_type == "delete":
        result = await session.execute(
            select(StravaActivity).where(StravaActivity.strava_id == event.object_id)
        )
        existing = result.scalar_one_or_none()
        if existing:
            await session.delete(existing)
            await session.commit()
            logger.info("strava_activity_deleted", strava_id=event.object_id)

    return {"status": "ok"}


# ── GET /v1/strava/activities ─────────────────────────────────────────────────


@router.get("/v1/strava/activities", response_model=ActivityListResponse)
@limiter.limit(strava_limit)
async def list_activities(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> ActivityListResponse:
    """List cached Strava activities, newest first."""
    count_result = await session.execute(select(func.count(StravaActivity.id)))
    total = count_result.scalar() or 0

    result = await session.execute(
        select(StravaActivity)
        .order_by(StravaActivity.started_at.desc())
        .offset(offset)
        .limit(limit)
    )
    activities = list(result.scalars().all())

    return ActivityListResponse(
        activities=[_activity_to_response(a) for a in activities],
        total=total,
    )
