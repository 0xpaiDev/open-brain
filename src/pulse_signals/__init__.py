"""Signal-driven morning-pulse pipeline (Phase 1).

Public entry points used by the pulse job/route:
  - build_morning_context(session, settings, http) -> MorningContext
  - run_detectors(ctx, settings)                   -> list[Signal]
  - select_signal(signals, threshold, order)       -> Signal | None
  - render_signal(signal, llm, today)              -> str
"""

from src.pulse_signals.context import MorningContext, build_morning_context
from src.pulse_signals.ranker import Signal, run_detectors, select_signal
from src.pulse_signals.render import render_signal

__all__ = [
    "MorningContext",
    "Signal",
    "build_morning_context",
    "render_signal",
    "run_detectors",
    "select_signal",
]
