"""Signal renderer: one Haiku call per fired signal, signal-specific prompt.

All variable content is wrapped in <user_input>...</user_input> delimiters;
the system prompt tells Haiku to treat it as data only. A failure falls back
to the legacy default so the pulse still ships.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import structlog

from src.pulse_signals.prompts import (
    focus_system_prompt,
    open_system_prompt,
    opportunity_system_prompt,
)
from src.pulse_signals.ranker import Signal

logger = structlog.get_logger(__name__)

_MAX_TOKENS = 80
_FALLBACK = "What's one thing you want to accomplish today?"

_PROMPT_BUILDERS: dict[str, Any] = {
    "focus": focus_system_prompt,
    "opportunity": opportunity_system_prompt,
    "open": open_system_prompt,
}


def _build_user_content(signal: Signal) -> str:
    safe_payload = json.dumps(signal.payload, default=str, ensure_ascii=False)
    return (
        f"Signal type: {signal.signal_type}\n"
        f"<user_input>{safe_payload}</user_input>"
    )


async def render_signal(signal: Signal, *, llm: Any | None, today: date) -> str:
    """Render a one-liner for `signal`. Falls back to the default on any failure."""
    try:
        prompt_builder = _PROMPT_BUILDERS[signal.signal_type]
    except KeyError:
        raise

    if llm is None:
        return _FALLBACK

    system_prompt = prompt_builder(today)
    user_content = _build_user_content(signal)

    try:
        raw = await llm.complete(
            system_prompt=system_prompt,
            user_content=user_content,
            max_tokens=_MAX_TOKENS,
        )
    except Exception as exc:
        logger.exception(
            "pulse_render_failed", signal_type=signal.signal_type, error=str(exc)
        )
        return _FALLBACK

    cleaned = (raw or "").strip().strip('"').strip("'")
    if not cleaned:
        return _FALLBACK
    # For "open" we want a question; other signal types may end in "." as remarks.
    if signal.signal_type == "open" and not cleaned.endswith("?"):
        cleaned = cleaned.rstrip(".!") + "?"
    return cleaned
