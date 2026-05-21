"""Deadline detector — fires when todos are due today."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import TodoItem
from src.pulse_signals.context import MorningContext
from src.pulse_signals.ranker import Signal

NAME = "deadline"
_URGENCY = 8.0
_MAX_TITLES = 3


async def detect(ctx: MorningContext, *, session: AsyncSession) -> Signal | None:
    day_start = datetime(ctx.today.year, ctx.today.month, ctx.today.day, tzinfo=UTC)
    day_end = day_start + timedelta(days=1)

    stmt = (
        select(TodoItem)
        .where(
            TodoItem.status == "open",
            TodoItem.due_date >= day_start,
            TodoItem.due_date < day_end,
        )
        .order_by(TodoItem.due_date)
    )
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        return None

    titles = [r.description for r in rows[:_MAX_TITLES]]
    return Signal(
        signal_type=NAME,
        urgency=_URGENCY,
        payload={
            "titles": titles,
            "total_count": len(rows),
        },
    )
