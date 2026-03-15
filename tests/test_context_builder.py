"""Unit tests for src/retrieval/context_builder.py.

All tests call build_context() directly — no DB, no mocks beyond the
autouse set_test_env fixture (which ensures settings is initialised).
SearchResult objects are constructed inline (plain dataclass).
"""

from datetime import UTC, datetime

import tiktoken

from src.retrieval.context_builder import ContextResult, build_context
from src.retrieval.search import SearchResult

# ── Helper ────────────────────────────────────────────────────────────────────


def _make_result(
    content: str,
    *,
    summary: str | None = None,
    type: str = "memory",
    combined_score: float = 0.9,
    created_at: datetime | None = None,
) -> SearchResult:
    return SearchResult(
        id="00000000-0000-0000-0000-000000000001",
        content=content,
        summary=summary,
        type=type,
        importance_score=0.5,
        combined_score=combined_score,
        created_at=created_at or datetime(2026, 3, 15, tzinfo=UTC),
    )


_ENCODER = tiktoken.get_encoding("cl100k_base")


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_build_context_happy_path():
    """3 short items well within budget are all included."""
    results = [
        _make_result("Short memory one."),
        _make_result("Short memory two."),
        _make_result("Short memory three."),
    ]
    ctx = build_context(results, token_budget=8192)

    assert ctx.items_included == 3
    assert ctx.items_truncated == 0
    assert ctx.tokens_used > 0
    assert ctx.tokens_used <= 8192
    assert ctx.tokens_budget == 8192
    assert "[1]" in ctx.context
    assert "[2]" in ctx.context
    assert "[3]" in ctx.context


def test_build_context_empty_results():
    """Empty input → empty context, all counts zero."""
    ctx = build_context([], token_budget=8192)

    assert ctx.context == ""
    assert ctx.tokens_used == 0
    assert ctx.items_included == 0
    assert ctx.items_truncated == 0
    assert ctx.tokens_budget == 8192


def test_build_context_single_item():
    """Single result is formatted and included."""
    ctx = build_context([_make_result("Just one memory.")], token_budget=8192)

    assert ctx.items_included == 1
    assert ctx.context.startswith("[1] TYPE:")


def test_build_context_respects_token_budget():
    """With a very tight budget, far fewer items are included."""
    results = [
        _make_result(f"Memory item number {i} with some text to fill tokens.") for i in range(10)
    ]
    ctx = build_context(results, token_budget=50)

    assert ctx.tokens_used <= 50
    assert ctx.items_included < 10


def test_build_context_single_item_exceeds_budget():
    """A single item that is longer than the budget is truncated."""
    long_content = "word " * 100  # ~100+ tokens
    ctx = build_context([_make_result(long_content)], token_budget=20)

    # Truncated item is still included (non-empty)
    assert ctx.items_included == 1
    assert ctx.items_truncated == 1
    assert ctx.tokens_used <= 22  # budget + small separator buffer
    assert ctx.context != ""


def test_build_context_uses_settings_budget(set_test_env):
    """Passing token_budget=None uses settings.context_token_budget."""
    from src.core import config as _config

    expected_budget = _config.settings.context_token_budget
    ctx = build_context([_make_result("Test content.")], token_budget=None)

    assert ctx.tokens_budget == expected_budget


def test_build_context_explicit_budget_overrides_settings():
    """Explicit token_budget takes precedence over settings value."""
    ctx = build_context([_make_result("Test content.")], token_budget=100)

    assert ctx.tokens_budget == 100


def test_build_context_summary_included_when_present():
    """Summary line appears in context when result.summary is not None."""
    result = _make_result("Main content.", summary="Short summary.")
    ctx = build_context([result], token_budget=8192)

    assert "Summary:" in ctx.context
    assert "Short summary." in ctx.context


def test_build_context_summary_omitted_when_none():
    """Summary line is absent when result.summary is None."""
    result = _make_result("Main content.", summary=None)
    ctx = build_context([result], token_budget=8192)

    assert "Summary:" not in ctx.context


def test_build_context_tokens_used_matches_actual_encoding():
    """tokens_used is within ±5 tokens of re-encoding the full context string.

    BPE tokenization is not perfectly additive across concatenation boundaries,
    so a small tolerance is acceptable.
    """
    results = [
        _make_result("The Python packaging ecosystem uses pyproject.toml."),
        _make_result("We decided to use Supabase for managed PostgreSQL."),
    ]
    ctx = build_context(results, token_budget=8192)

    actual_tokens = len(_ENCODER.encode(ctx.context))
    assert abs(ctx.tokens_used - actual_tokens) <= 5


def test_build_context_context_result_fields():
    """ContextResult has all five fields with correct types."""
    ctx = build_context([_make_result("Content.")], token_budget=8192)

    assert isinstance(ctx, ContextResult)
    assert isinstance(ctx.context, str)
    assert isinstance(ctx.tokens_used, int)
    assert isinstance(ctx.tokens_budget, int)
    assert isinstance(ctx.items_included, int)
    assert isinstance(ctx.items_truncated, int)


def test_build_context_date_formatted_in_block():
    """Block header contains the date in YYYY-MM-DD format."""
    result = _make_result("Content.", created_at=datetime(2025, 6, 1, tzinfo=UTC))
    ctx = build_context([result], token_budget=8192)

    assert "2025-06-01" in ctx.context


def test_build_context_budget_zero_returns_empty():
    """Zero token budget produces empty context."""
    ctx = build_context([_make_result("Some content.")], token_budget=0)

    assert ctx.context == ""
    assert ctx.tokens_used == 0
    assert ctx.items_included == 0
