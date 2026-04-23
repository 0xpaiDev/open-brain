"""Opportunity detector.

Phase 1 definition (weather-only): today is dry, the next three days are wet.
Fires ~1-2x/week in temperate climates. When weather data is unavailable the
detector returns None so the ranker falls through.
"""

from __future__ import annotations

from src.pulse_signals.context import MorningContext
from src.pulse_signals.ranker import Signal

NAME = "opportunity"
_TODAY_DRY_MM = 0.3
_NEXT_DAYS_WET_MM = 2.0
_LOOKAHEAD_DAYS = 3
_URGENCY = 6.0


def detect(ctx: MorningContext) -> Signal | None:
    w = ctx.weather
    if w is None:
        return None

    if w.today_precip_mm > _TODAY_DRY_MM:
        return None

    window = w.next_7_days[:_LOOKAHEAD_DAYS]
    if not window:
        return None

    worst = max(d.precip_mm for d in window)
    if worst < _NEXT_DAYS_WET_MM:
        return None

    return Signal(
        signal_type=NAME,
        urgency=_URGENCY,
        payload={
            "today_min_temp": w.today_min_temp,
            "today_max_temp": w.today_max_temp,
            "today_precip_mm": w.today_precip_mm,
            "worst_next_3_precip_mm": worst,
        },
    )
