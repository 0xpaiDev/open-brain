"""Commitment pace detector — fires when an aggregate commitment is behind or well ahead of pace."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routes.commitments import _compute_pace
from src.core.models import Commitment
from src.pulse_signals.context import MorningContext
from src.pulse_signals.ranker import Signal

NAME = "commitment_pace"
_URGENCY = 7.5
_BEHIND_THRESHOLD = 0.85
_AHEAD_THRESHOLD = 1.2


async def detect(ctx: MorningContext, *, session: AsyncSession) -> Signal | None:
    stmt = select(Commitment).where(
        Commitment.cadence == "aggregate",
        Commitment.status == "active",
        Commitment.start_date <= ctx.today,
        Commitment.end_date >= ctx.today,
    )
    rows = (await session.execute(stmt)).scalars().all()

    for c in rows:
        pace = _compute_pace(c.targets, c.progress, c.start_date, c.end_date, ctx.today)
        if pace is None:
            continue
        overall = pace.get("overall", 0.0)
        if overall < _BEHIND_THRESHOLD or overall > _AHEAD_THRESHOLD:
            primary_metric = next(
                (k for k in (c.targets or {}) if k != "overall"), "overall"
            )
            return Signal(
                signal_type=NAME,
                urgency=_URGENCY,
                payload={
                    "name": c.name,
                    "metric": primary_metric,
                    "actual": (c.progress or {}).get(primary_metric, 0.0),
                    "target": (c.targets or {}).get(primary_metric, 0.0),
                    "pace_overall": round(overall, 2),
                    "is_behind": overall < _BEHIND_THRESHOLD,
                },
            )
    return None
