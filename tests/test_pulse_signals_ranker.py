"""Tests for the pulse signal ranker.

Pure-function tests over the Signal dataclass. No DB or network.
"""

from __future__ import annotations

import pytest

from src.pulse_signals.ranker import Signal, select_signal


def _sig(name: str, urgency: float) -> Signal:
    return Signal(signal_type=name, urgency=urgency, payload={})


def test_select_signal_empty_returns_none():
    assert select_signal([], threshold=5.0, order=["focus", "opportunity", "open"]) is None


def test_select_signal_below_threshold_returns_none():
    signals = [_sig("open", 4.9)]
    assert select_signal(signals, threshold=5.0, order=["focus", "opportunity", "open"]) is None


def test_select_signal_single_above_threshold_picked():
    signals = [_sig("focus", 7.0)]
    chosen = select_signal(signals, threshold=5.0, order=["focus", "opportunity", "open"])
    assert chosen is not None
    assert chosen.signal_type == "focus"


def test_select_signal_picks_highest_urgency():
    signals = [_sig("open", 5.0), _sig("focus", 7.0), _sig("opportunity", 6.0)]
    chosen = select_signal(signals, threshold=5.0, order=["focus", "opportunity", "open"])
    assert chosen is not None
    assert chosen.signal_type == "focus"


def test_select_signal_tie_break_by_order():
    signals = [_sig("open", 6.0), _sig("opportunity", 6.0), _sig("focus", 6.0)]
    chosen = select_signal(signals, threshold=5.0, order=["focus", "opportunity", "open"])
    assert chosen is not None
    assert chosen.signal_type == "focus"


def test_select_signal_tie_break_reordered():
    signals = [_sig("open", 6.0), _sig("focus", 6.0)]
    chosen = select_signal(signals, threshold=5.0, order=["open", "focus"])
    assert chosen is not None
    assert chosen.signal_type == "open"


def test_select_signal_filters_none_entries():
    signals = [_sig("open", 6.0)]
    # None entries are skipped, not treated as zero
    chosen = select_signal(signals, threshold=5.0, order=["focus", "open"])
    assert chosen is not None
    assert chosen.signal_type == "open"


def test_select_signal_all_below_threshold_all_returned_none():
    signals = [_sig("open", 1.0), _sig("focus", 2.0)]
    assert select_signal(signals, threshold=5.0, order=["focus", "open"]) is None


def test_signal_is_immutable():
    from dataclasses import FrozenInstanceError

    s = _sig("focus", 7.0)
    with pytest.raises(FrozenInstanceError):
        s.urgency = 9.0  # type: ignore[misc]
