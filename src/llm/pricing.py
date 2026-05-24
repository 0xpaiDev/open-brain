"""LLM cost computation.

Rates are per million tokens in USD. Update PRICING_VERSION and the dict
whenever Anthropic changes pricing — old rows retain the version they were
computed with so historical cost stays stable.
"""

from decimal import Decimal

PRICING_VERSION = "2026-05"

# Per-million-token USD rates
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-7": {
        "input": 15.00,
        "output": 75.00,
        "cache_read": 1.50,
        "cache_write": 18.75,
    },
    "claude-sonnet-4-6": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "claude-haiku-4-5": {
        "input": 1.00,
        "output": 5.00,
        "cache_read": 0.10,
        "cache_write": 1.25,
    },
    "claude-haiku-4-5-20251001": {
        "input": 1.00,
        "output": 5.00,
        "cache_read": 0.10,
        "cache_write": 1.25,
    },
}

_UNKNOWN_MODEL_COST = Decimal("0")


def compute_cost_usd(model: str, usage: object) -> Decimal:
    """Compute USD cost from an Anthropic usage object.

    Falls back to zero for unknown models so recording never raises.
    """
    rates = PRICING.get(model)
    if rates is None:
        return _UNKNOWN_MODEL_COST

    input_tokens: int = getattr(usage, "input_tokens", 0) or 0
    output_tokens: int = getattr(usage, "output_tokens", 0) or 0
    cache_read: int = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write: int = getattr(usage, "cache_creation_input_tokens", 0) or 0

    return (
        Decimal(str(input_tokens * rates["input"] / 1_000_000))
        + Decimal(str(output_tokens * rates["output"] / 1_000_000))
        + Decimal(str(cache_read * rates["cache_read"] / 1_000_000))
        + Decimal(str(cache_write * rates["cache_write"] / 1_000_000))
    ).quantize(Decimal("0.000001"))
