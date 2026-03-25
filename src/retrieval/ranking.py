"""Ranking functions for hybrid search scoring.

All functions are pure — no I/O, no DB, no external dependencies.
Weights are read from settings (env vars) so they can be tuned without
code changes.
"""

import math

from src.core.config import get_settings




def recency_score(age_days: float) -> float:
    """Exponential decay score based on memory age.

    Returns 1.0 for age_days=0, decreasing toward 0 as age grows.
    Half-life is configured via settings.importance_recency_half_life_days.

    Args:
        age_days: How many days old the memory is (0 = today).

    Returns:
        Float in [0, 1].
    """
    s = get_settings()
    return math.exp(-age_days / s.importance_recency_half_life_days)


def combined_score(
    vector_score: float,
    keyword_score: float,
    importance_score: float,
    recency_score_val: float,
) -> float:
    """Weighted combination of the four ranking signals.

    Weights come from settings and must sum to 1.0:
        vector_weight + keyword_weight + importance_weight + recency_weight = 1.0

    Args:
        vector_score: Cosine similarity score, normalised to [0, 1].
        keyword_score: FTS BM25 / TF-IDF score, normalised to [0, 1].
        importance_score: 0.6 * base_importance + 0.4 * dynamic_importance.
        recency_score_val: Output of recency_score(), in [0, 1].

    Returns:
        Combined float score in [0, 1].
    """
    s = get_settings()
    return (
        s.search_vector_weight * vector_score
        + s.search_keyword_weight * keyword_score
        + s.search_importance_weight * importance_score
        + s.search_recency_weight * recency_score_val
    )
