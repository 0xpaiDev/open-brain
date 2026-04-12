"""Tests for CP8: ranking pure functions.

All tests are purely computational — no DB or external APIs needed.
"""

import math

import pytest

from src.retrieval.ranking import combined_score, recency_score

# ── recency_score ─────────────────────────────────────────────────────────────


def test_recency_score_is_between_0_and_1():
    """recency_score always returns a value in [0, 1]."""
    assert 0.0 <= recency_score(0) <= 1.0
    assert 0.0 <= recency_score(1) <= 1.0
    assert 0.0 <= recency_score(30) <= 1.0
    assert 0.0 <= recency_score(365) <= 1.0


def test_recency_score_decreases_over_time():
    """Older memories score lower than recent ones."""
    score_1_day = recency_score(1)
    score_30_days = recency_score(30)
    score_180_days = recency_score(180)
    assert score_1_day > score_30_days > score_180_days


def test_recency_score_today_is_one():
    """A memory from today (age_days=0) scores 1.0."""
    assert recency_score(0) == pytest.approx(1.0)


def test_recency_score_uses_half_life():
    """After half_life_days, score should be ~0.5 (exp(-1) * correction)."""
    # Default half_life is 30 days: exp(-30/30) = exp(-1) ≈ 0.368
    # Not exactly 0.5, but the decay is exponential, not halving
    score = recency_score(30)
    expected = math.exp(-1.0)
    assert score == pytest.approx(expected, rel=1e-3)


# ── combined_score ────────────────────────────────────────────────────────────


def test_combined_score_weights_sum_to_one():
    """Vector + keyword + importance + recency weights must sum to 1.0."""
    from src.core.config import settings

    total = (
        settings.search_vector_weight
        + settings.search_keyword_weight
        + settings.search_importance_weight
        + settings.search_recency_weight
    )
    assert total == pytest.approx(1.0, abs=0.001)


def test_combined_score_with_zero_inputs():
    """All-zero inputs return 0.0."""
    score = combined_score(
        vector_score=0.0,
        keyword_score=0.0,
        importance_score=0.0,
        recency_score_val=0.0,
    )
    assert score == pytest.approx(0.0)


def test_combined_score_with_perfect_inputs():
    """All-one inputs return 1.0."""
    score = combined_score(
        vector_score=1.0,
        keyword_score=1.0,
        importance_score=1.0,
        recency_score_val=1.0,
    )
    assert score == pytest.approx(1.0)


def test_combined_score_uses_configured_weights():
    """combined_score uses weights from settings, not hardcoded values."""
    from src.core.config import settings

    score = combined_score(
        vector_score=1.0,
        keyword_score=0.0,
        importance_score=0.0,
        recency_score_val=0.0,
    )
    # Only vector component contributes
    assert score == pytest.approx(settings.search_vector_weight)
