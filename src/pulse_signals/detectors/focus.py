"""Focus detector.

Fires when today's calendar contains an event whose title matches any of the
configured focus keywords (case-insensitive substring). Urgency scales gently
with the number of distinct matches so a "1:1 + demo" day beats a single "1:1".
"""

from __future__ import annotations

from src.pulse_signals.context import MorningContext
from src.pulse_signals.ranker import Signal

NAME = "focus"
_BASE_URGENCY = 7.0
_PER_MATCH_BONUS = 0.5
_URGENCY_CAP = 9.0


def detect(ctx: MorningContext, *, keywords: list[str]) -> Signal | None:
    if not keywords:
        return None

    events = ctx.calendar.events if ctx.calendar else []
    if not events:
        return None

    normalized = [k.lower() for k in keywords]
    matched: list[tuple[str, str, str]] = []  # (keyword, event_title, event_start)

    for event in events:
        title = event.title or ""
        title_lc = title.lower()
        for kw in normalized:
            if kw and kw in title_lc:
                matched.append((kw, title, event.start))
                break

    if not matched:
        return None

    first_kw, first_title, first_start = matched[0]
    urgency = min(_URGENCY_CAP, _BASE_URGENCY + _PER_MATCH_BONUS * max(0, len(matched) - 1))

    return Signal(
        signal_type=NAME,
        urgency=urgency,
        payload={
            "event_title": first_title,
            "event_start": first_start,
            "reason": f"keyword:{first_kw}",
            "match_count": len(matched),
        },
    )
