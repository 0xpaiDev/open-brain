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
    commitment_pace_system_prompt,
    focus_system_prompt,
    opportunity_system_prompt,
)
from src.pulse_signals.ranker import Signal

logger = structlog.get_logger(__name__)

_MAX_TOKENS = 80
_FALLBACK = "What's one thing you want to accomplish today?"

_PROMPT_BUILDERS: dict[str, Any] = {
    "focus": focus_system_prompt,
    "opportunity": opportunity_system_prompt,
    "open": None,  # open is template-only; no LLM call
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

    # Template-only signals (e.g. "open") skip the LLM entirely.
    if prompt_builder is None:
        return _FALLBACK

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
    return cleaned


# ---------------------------------------------------------------------------
# build_briefing — multi-signal bullet assembler
# ---------------------------------------------------------------------------

_BRIEFING_FALLBACK = "• Clear schedule — nothing due or scheduled"

_BRIEFING_PROMPT_BUILDERS: dict[str, Any] = {
    "focus": focus_system_prompt,
    "opportunity": opportunity_system_prompt,
    "commitment_pace": commitment_pace_system_prompt,
}


def _deadline_bullet(payload: dict) -> str:
    titles = payload.get("titles", [])
    total = payload.get("total_count", len(titles))
    title_str = ", ".join(titles)
    suffix = "…" if total > len(titles) else ""
    noun = "task" if total == 1 else "tasks"
    return f"• {total} {noun} due today: {title_str}{suffix}"


def _named_day_bullet(payload: dict) -> str:
    titles = payload.get("titles", [])
    return "• Today: " + ", ".join(titles)


def _open_bullet(payload: dict) -> str:
    todo_count = payload.get("todo_count", 0)
    event_count = payload.get("event_count", 0)
    if todo_count > 0 and event_count > 0:
        return f"• {todo_count} open tasks · {event_count} event(s) today"
    if todo_count > 0:
        return f"• {todo_count} open tasks — nothing else scheduled"
    return "• Clear schedule — nothing due or scheduled"


async def _llm_bullet(signal: Signal, *, llm: Any, today: date) -> str:
    builder = _BRIEFING_PROMPT_BUILDERS.get(signal.signal_type)
    if builder is None or llm is None:
        return _BRIEFING_FALLBACK

    system_prompt = builder(today)
    safe_payload = json.dumps(signal.payload, default=str, ensure_ascii=False)
    user_content = f"Signal type: {signal.signal_type}\n<user_input>{safe_payload}</user_input>"

    try:
        raw = await llm.complete(
            system_prompt=system_prompt,
            user_content=user_content,
            max_tokens=_MAX_TOKENS,
        )
    except Exception as exc:
        logger.exception(
            "pulse_briefing_llm_failed", signal_type=signal.signal_type, error=str(exc)
        )
        return _BRIEFING_FALLBACK

    cleaned = (raw or "").strip().strip('"').strip("'")
    return f"• {cleaned}" if cleaned else _BRIEFING_FALLBACK


_TEMPLATE_BUILDERS: dict[str, Any] = {
    "deadline": _deadline_bullet,
    "named_day": _named_day_bullet,
    "open": _open_bullet,
}
_LLM_SIGNAL_TYPES: frozenset[str] = frozenset({"focus", "opportunity", "commitment_pace"})


async def build_briefing(
    signals: list[Signal], *, llm: Any | None, today: date
) -> str:
    """Assemble a newline-separated bullet briefing from all passing signals."""
    if not signals:
        return _BRIEFING_FALLBACK

    bullets: list[str] = []
    for signal in signals:
        if signal.signal_type in _TEMPLATE_BUILDERS:
            bullets.append(_TEMPLATE_BUILDERS[signal.signal_type](signal.payload))
        elif signal.signal_type in _LLM_SIGNAL_TYPES:
            bullets.append(await _llm_bullet(signal, llm=llm, today=today))

    return "\n".join(bullets) if bullets else _BRIEFING_FALLBACK
