"""Strava webhook and activity endpoints.

GET    /v1/strava/webhook      — webhook verification (PUBLIC)
POST   /v1/strava/webhook      — webhook event receiver (PUBLIC, HMAC verified)
GET    /v1/strava/activities    — list cached activities (API key auth)
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import limiter, strava_limit
from src.core.database import get_db
from src.core.models import Commitment, CommitmentActivity, StravaActivity, StravaToken

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


# Metric mapping: target key → StravaActivity field
_METRIC_FIELD_MAP = {
    "km": ("distance_m", 0.001),       # distance_m → km
    "tss": ("tss", 1.0),
    "minutes": ("duration_s", 1 / 60),  # seconds → minutes
    "hours": ("duration_s", 1 / 3600),  # seconds → hours
    "elevation_m": ("elevation_m", 1.0),
}


async def update_commitment_progress(
    session: AsyncSession, commitment: Commitment
) -> None:
    """Recalculate aggregate commitment progress from all linked activities.

    Always recalculates from scratch (not incremental) to stay safe
    against race conditions and Strava update/delete events.
    """
    if not commitment.targets:
        return

    # Fetch all linked activities

    result = await session.execute(
        select(StravaActivity)
        .join(CommitmentActivity, CommitmentActivity.strava_activity_id == StravaActivity.id)
        .where(CommitmentActivity.commitment_id == commitment.id)
    )
    activities = list(result.scalars().all())

    progress: dict[str, float] = {}
    for metric_key in commitment.targets:
        mapping = _METRIC_FIELD_MAP.get(metric_key)
        if not mapping:
            continue
        field_name, multiplier = mapping
        total = sum(
            (getattr(a, field_name, None) or 0) * multiplier
            for a in activities
        )
        progress[metric_key] = round(total, 2)

    commitment.progress = progress


async def _link_activity_to_commitments(
    session: AsyncSession, activity: StravaActivity
) -> None:
    """Find active aggregate commitments matching this activity's date and link them."""
    activity_date = activity.started_at.date()

    result = await session.execute(
        select(Commitment).where(
            Commitment.cadence == "aggregate",
            Commitment.status == "active",
            Commitment.start_date <= activity_date,
            Commitment.end_date >= activity_date,
        )
    )
    commitments = list(result.scalars().all())

    for commitment in commitments:
        # Insert junction row (ignore if already exists — dedup)
        existing = await session.execute(
            select(CommitmentActivity).where(
                CommitmentActivity.commitment_id == commitment.id,
                CommitmentActivity.strava_activity_id == activity.id,
            )
        )
        if existing.scalar_one_or_none() is None:
            session.add(CommitmentActivity(
                commitment_id=commitment.id,
                strava_activity_id=activity.id,
            ))
            await session.flush()

        # Recalculate progress
        await update_commitment_progress(session, commitment)

    if commitments:
        await session.commit()
        logger.info(
            "commitment_progress_updated",
            strava_id=activity.strava_id,
            commitment_count=len(commitments),
        )


async def _unlink_activity_from_commitments(
    session: AsyncSession, strava_activity_id
) -> None:
    """Remove junction rows for a deleted activity and recalculate progress."""
    from sqlalchemy import delete as sa_delete

    # Find affected commitments before removing links
    result = await session.execute(
        select(CommitmentActivity.commitment_id).where(
            CommitmentActivity.strava_activity_id == strava_activity_id
        )
    )
    affected_commitment_ids = [row[0] for row in result.all()]

    if not affected_commitment_ids:
        return

    # Delete junction rows
    await session.execute(
        sa_delete(CommitmentActivity).where(
            CommitmentActivity.strava_activity_id == strava_activity_id
        )
    )

    # Recalculate progress for affected commitments
    for cid in affected_commitment_ids:
        commitment = await session.get(Commitment, cid)
        if commitment and commitment.status == "active":
            await update_commitment_progress(session, commitment)


async def _get_valid_access_token(session: AsyncSession) -> str | None:
    """Return a valid Strava access token, refreshing if needed.

    On first call, bootstraps from env vars into the strava_tokens table.
    On subsequent calls, refreshes via OAuth if the token has expired.
    """
    settings = _get_settings()

    # Look for existing token row
    result = await session.execute(select(StravaToken).limit(1))
    token_row = result.scalar_one_or_none()

    if token_row is None:
        # Bootstrap from env vars
        access = settings.strava_access_token.get_secret_value()
        refresh = settings.strava_refresh_token.get_secret_value()
        if not access or not refresh:
            logger.warning("strava_no_env_tokens")
            return None
        token_row = StravaToken(
            access_token=access,
            refresh_token=refresh,
            # Assume env token is fresh; will refresh on next expiry
            expires_at=datetime.now(timezone.utc),
        )
        session.add(token_row)
        await session.commit()
        await session.refresh(token_row)
        logger.info("strava_tokens_bootstrapped")

    # Check if token is still valid (60s buffer)
    now = datetime.now(timezone.utc)
    if token_row.expires_at.tzinfo is None:
        expires = token_row.expires_at.replace(tzinfo=timezone.utc)
    else:
        expires = token_row.expires_at

    if expires > now + timedelta(seconds=60):
        return token_row.access_token

    # Refresh the token
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://www.strava.com/api/v3/oauth/token",
                data={
                    "client_id": settings.strava_client_id,
                    "client_secret": settings.strava_client_secret.get_secret_value(),
                    "grant_type": "refresh_token",
                    "refresh_token": token_row.refresh_token,
                },
                timeout=10.0,
            )
            if resp.status_code != 200:
                logger.warning("strava_token_refresh_failed", status=resp.status_code)
                # Fall back to current token (might still work)
                return token_row.access_token

            data = resp.json()
            token_row.access_token = data["access_token"]
            token_row.refresh_token = data["refresh_token"]
            token_row.expires_at = datetime.fromtimestamp(
                data["expires_at"], tz=timezone.utc
            )
            if data.get("athlete", {}).get("id"):
                token_row.athlete_id = data["athlete"]["id"]
            await session.commit()
            await session.refresh(token_row)
            logger.info("strava_token_refreshed", expires_at=str(token_row.expires_at))
            return token_row.access_token
    except Exception:
        logger.warning("strava_token_refresh_error", exc_info=True)
        return token_row.access_token


async def _fetch_and_upsert_activity(
    session: AsyncSession, activity_id: int
) -> StravaActivity | None:
    """Fetch activity details from Strava API and upsert into database."""
    settings = _get_settings()
    access_token = await _get_valid_access_token(session)
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

    # Calculate TSS from normalized power (weighted_average_watts) and FTP
    np_watts = data.get("weighted_average_watts")
    moving_time = data.get("moving_time")
    ftp = settings.strava_ftp
    tss = None
    tss_method = None
    if np_watts and moving_time and ftp:
        intensity_factor = np_watts / ftp
        tss = round((moving_time * np_watts * intensity_factor) / (ftp * 3600) * 100, 1)
        tss_method = "power"
    else:
        # Fallback: estimate TSS from heart rate reserve when power meter absent
        avg_hr = data.get("average_heartrate")
        max_hr = settings.strava_max_hr
        resting_hr = settings.strava_resting_hr
        if avg_hr and max_hr and resting_hr and moving_time:
            rpe = (avg_hr - resting_hr) / (max_hr - resting_hr)
            if rpe > 0:
                tss = round((moving_time / 3600) * rpe * 100, 1)
                tss_method = "hr_estimate"

    if tss is None:
        logger.warning(
            "strava_tss_unavailable",
            activity_id=activity_id,
            np_watts=np_watts,
            moving_time=moving_time,
        )

    if existing:
        existing.activity_type = data.get("type")
        existing.name = data.get("name")
        existing.distance_m = data.get("distance")
        existing.duration_s = data.get("moving_time")
        existing.tss = tss
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
            tss=tss,
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
        tss=tss,
        tss_method=tss_method,
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

    # Verify HMAC signature if Strava sends one.
    # Strava webhook POSTs may not include a signature header — the
    # subscription is authenticated via the verify_token handshake instead.
    settings = _get_settings()
    client_secret = settings.strava_client_secret.get_secret_value()
    signature = request.headers.get("X-Hub-Signature", "")
    if signature and client_secret:
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

    logger.info(
        "strava_webhook_received",
        object_type=event.object_type,
        aspect_type=event.aspect_type,
        object_id=event.object_id,
    )

    if event.object_type != "activity":
        return {"status": "ignored"}

    if event.aspect_type in ("create", "update"):
        activity = await _fetch_and_upsert_activity(session, event.object_id)
        if activity:
            await _link_activity_to_commitments(session, activity)

            # Best-effort: sync activity to memory for RAG search
            try:
                from src.llm.client import embedding_client
                from src.pipeline.training_sync import sync_strava_activity_to_memory

                if embedding_client:
                    await sync_strava_activity_to_memory(session, activity, embedding_client)
            except Exception:
                logger.warning(
                    "strava_activity_memory_sync_failed",
                    strava_id=event.object_id,
                    exc_info=True,
                )

    elif event.aspect_type == "delete":
        result = await session.execute(
            select(StravaActivity).where(StravaActivity.strava_id == event.object_id)
        )
        existing = result.scalar_one_or_none()
        if existing:
            # Supersede memory before deleting the activity
            try:
                from src.pipeline.training_sync import supersede_memory_for_strava_activity

                await supersede_memory_for_strava_activity(session, existing.strava_id)
            except Exception:
                logger.warning(
                    "strava_memory_supersede_failed",
                    strava_id=event.object_id,
                    exc_info=True,
                )

            await _unlink_activity_from_commitments(session, existing.id)
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
