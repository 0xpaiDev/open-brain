"""Context builder: format search results into a token-budgeted LLM context string.

The main entry point is build_context(). It:
1. Iterates over SearchResult objects sorted by combined_score descending (caller's responsibility)
2. Formats each item as a numbered block
3. Accumulates blocks until the token budget is exhausted
4. Returns a ContextResult with the context string and metadata

All functions are synchronous — tiktoken is CPU-only with no I/O.
"""

from dataclasses import dataclass

import tiktoken

from src.core.config import get_settings
from src.retrieval.search import SearchResult

_ENCODER = tiktoken.get_encoding("cl100k_base")


@dataclass
class ContextResult:
    """Result from build_context()."""

    context: str
    tokens_used: int
    tokens_budget: int
    items_included: int
    items_truncated: int




def _format_item(index: int, result: SearchResult) -> str:
    """Format a single SearchResult as a numbered context block.

    Args:
        index: 1-based position in the context (drives the [N] label).
        result: The search result to format.

    Returns:
        A multi-line string block for this memory item.
    """
    date_str = result.created_at.strftime("%Y-%m-%d") if result.created_at else "unknown"
    lines = [
        f"[{index}] TYPE: {result.type} | {date_str}",
        f"Content: {result.content}",
    ]
    if result.summary is not None:
        lines.append(f"Summary: {result.summary}")
    return "\n".join(lines)


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to at most max_tokens tokens using tiktoken.

    Uses encode + decode so the result is always valid UTF-8.

    Args:
        text: Input string.
        max_tokens: Maximum number of tokens to keep.

    Returns:
        Truncated string. Empty string if max_tokens <= 0.
    """
    if max_tokens <= 0:
        return ""
    tokens = _ENCODER.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return _ENCODER.decode(tokens[:max_tokens])


def build_context(
    results: list[SearchResult],
    token_budget: int | None = None,
) -> ContextResult:
    """Format search results into a token-budgeted context string for LLM injection.

    Iterates over results (expected to be pre-sorted by combined_score descending)
    and greedily includes each item until the token budget would be exceeded. On the
    first item that doesn't fit, it is truncated to the remaining budget; if the
    truncated result is non-empty it is included and the loop stops.

    Token counts are accumulated per-item (not by re-encoding the full string).
    The final tokens_used may differ from re-encoding the full context string by
    a small margin (±5 tokens) due to BPE boundary effects at concatenation points.

    Args:
        results: Search results to format, sorted by combined_score descending.
        token_budget: Maximum tokens for the context string. Defaults to
            settings.context_token_budget (8192).

    Returns:
        ContextResult with the formatted context string and metadata.
    """
    budget = token_budget if token_budget is not None else get_settings().context_token_budget

    if not results:
        return ContextResult(
            context="",
            tokens_used=0,
            tokens_budget=budget,
            items_included=0,
            items_truncated=0,
        )

    included_blocks: list[str] = []
    tokens_used = 0
    items_truncated = 0

    for i, result in enumerate(results):
        block = _format_item(i + 1, result)
        block_tokens = len(_ENCODER.encode(block))
        # Separator cost: "\n\n" between blocks (conservative 2-token estimate)
        sep_cost = 2 if included_blocks else 0
        remaining = budget - tokens_used

        if block_tokens + sep_cost <= remaining:
            included_blocks.append(block)
            tokens_used += block_tokens + sep_cost
        else:
            # Try to include a truncated version
            truncated = _truncate_to_tokens(block, remaining - sep_cost)
            if truncated:
                included_blocks.append(truncated)
                tokens_used += len(_ENCODER.encode(truncated)) + sep_cost
                items_truncated += 1
            # Budget exhausted — stop regardless of whether truncation succeeded
            break

    context = "\n\n".join(included_blocks)
    return ContextResult(
        context=context,
        tokens_used=tokens_used,
        tokens_budget=budget,
        items_included=len(included_blocks),
        items_truncated=items_truncated,
    )
