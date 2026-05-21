"""Open detector — always-on fallback.

Produces a template bullet summarising open todos and calendar events.
No LLM call. Fires unconditionally so there is always at least one bullet
on a quiet day.
"""

from __future__ import annotations

from src.pulse_signals.context import MorningContext
from src.pulse_signals.ranker import Signal

NAME = "open"
_URGENCY = 5.0


def detect(ctx: MorningContext) -> Signal | None:
    todo_count = len(ctx.open_todos)
    event_count = len(ctx.calendar.events) if ctx.calendar else 0

    return Signal(
        signal_type=NAME,
        urgency=_URGENCY,
        payload={
            "todo_count": todo_count,
            "event_count": event_count,
        },
    )
