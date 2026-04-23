"""Open detector — Phase 1 catch-all.

Fires when the day has minimum activity (at least one open todo or one
calendar event). This is the architectural equivalent of today's generic
pulse: something to say, without a specific signal. Phase 2 will split this
into richer detectors and raise its urgency bar.
"""

from __future__ import annotations

from src.pulse_signals.context import MorningContext
from src.pulse_signals.ranker import Signal

NAME = "open"
_URGENCY = 5.0
_TOP_TODOS = 3


def detect(ctx: MorningContext) -> Signal | None:
    has_todos = bool(ctx.open_todos)
    has_events = bool(ctx.calendar.events) if ctx.calendar else False
    if not has_todos and not has_events:
        return None

    yesterday_question = (
        ctx.yesterday_pulse.ai_question
        if ctx.yesterday_pulse is not None
        else None
    )

    return Signal(
        signal_type=NAME,
        urgency=_URGENCY,
        payload={
            "top_todos": list(ctx.open_todos[:_TOP_TODOS]),
            "event_count": len(ctx.calendar.events) if ctx.calendar else 0,
            "yesterday_question": yesterday_question,
        },
    )
