"""Signal ranker.

Picks the max-urgency Signal above the silence threshold. Ties are broken by
detector order (from settings.pulse_signal_detectors). Detectors that return
None are ignored; run_detectors aggregates the raw outputs for analytics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from src.pulse_signals.context import MorningContext

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Signal:
    signal_type: str
    urgency: float
    payload: dict[str, Any] = field(default_factory=dict)


def _parse_order(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(",") if p.strip()]


def run_detectors(ctx: MorningContext, settings: Any) -> list[Signal]:
    """Invoke each configured detector; return all non-None Signals in detector order."""
    # Local imports to avoid a cycle at module load.
    from src.pulse_signals.detectors import focus as focus_detector
    from src.pulse_signals.detectors import open as open_detector
    from src.pulse_signals.detectors import opportunity as opportunity_detector

    keywords_raw = getattr(settings, "pulse_focus_keywords", "") or ""
    keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]

    order = _parse_order(getattr(settings, "pulse_signal_detectors", ""))
    signals: list[Signal] = []

    for name in order:
        try:
            if name == focus_detector.NAME:
                s = focus_detector.detect(ctx, keywords=keywords)
            elif name == opportunity_detector.NAME:
                s = opportunity_detector.detect(ctx)
            elif name == open_detector.NAME:
                s = open_detector.detect(ctx)
            else:
                logger.warning("unknown_pulse_detector", name=name)
                continue
        except Exception:
            logger.exception("pulse_detector_failed", name=name)
            continue
        if s is not None:
            signals.append(s)

    return signals


def select_signal(
    signals: list[Signal], threshold: float, order: list[str]
) -> Signal | None:
    """Pick the max-urgency signal at or above `threshold`.

    Tie-break: earlier position in `order` wins. Signals with an unknown type
    are sorted last (shouldn't happen in Phase 1 since run_detectors enforces
    the enum).
    """
    qualifying = [s for s in signals if s is not None and s.urgency >= threshold]
    if not qualifying:
        return None

    def key(s: Signal) -> tuple[float, int]:
        try:
            idx = order.index(s.signal_type)
        except ValueError:
            idx = len(order)
        return (-s.urgency, idx)

    qualifying.sort(key=key)
    return qualifying[0]


def trace(signals: list[Signal], order: list[str]) -> list[dict[str, Any]]:
    """Serialize Signals for DailyPulse.parsed_data['signal_trace']. Pure data."""
    out: list[dict[str, Any]] = []
    for name in order:
        match = next((s for s in signals if s.signal_type == name), None)
        if match is None:
            out.append({"signal_type": name, "fired": False})
        else:
            out.append(
                {
                    "signal_type": name,
                    "fired": True,
                    "urgency": match.urgency,
                    "payload": match.payload,
                }
            )
    return out
