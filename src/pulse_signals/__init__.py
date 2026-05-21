"""Signal-driven morning-pulse pipeline (Phase 1).

Public entry points used by the pulse job/route:
  - build_morning_context(session, settings, http) -> MorningContext
  - run_detectors(ctx, settings, *, session=None)   -> list[Signal]  (async)
  - select_signal(signals, threshold, order)       -> Signal | None
  - select_signals(signals, threshold, order)      -> list[Signal]
  - render_signal(signal, llm, today)              -> str
  - build_briefing(signals, llm, today)            -> str
"""

from src.pulse_signals.context import MorningContext, build_morning_context
from src.pulse_signals.ranker import Signal, run_detectors, select_signal, select_signals, trace
from src.pulse_signals.render import build_briefing, render_signal

__all__ = [
    "MorningContext",
    "build_morning_context",
    "Signal",
    "run_detectors",
    "select_signal",
    "select_signals",
    "trace",
    "build_briefing",
    "render_signal",
]
