"""Named-day detector — fires on all-day calendar events (birthdays, holidays)."""

from __future__ import annotations

from src.pulse_signals.context import MorningContext
from src.pulse_signals.ranker import Signal

NAME = "named_day"
_URGENCY = 6.5
_MAX_TITLES = 3


def detect(ctx: MorningContext) -> Signal | None:
    events = ctx.calendar.events if ctx.calendar else []
    all_day = [e for e in events if e.all_day]
    if not all_day:
        return None

    titles = [e.title for e in all_day[:_MAX_TITLES]]
    return Signal(
        signal_type=NAME,
        urgency=_URGENCY,
        payload={"titles": titles},
    )
