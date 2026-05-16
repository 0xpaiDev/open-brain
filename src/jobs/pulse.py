"""Morning Pulse cron job.

Calls POST /v1/pulse/start each morning to run the signal pipeline and
create today's pulse record. The web dashboard surfaces the result.

Usage (cron / docker compose run):
    python -m src.jobs.pulse

Cron setup (host cron, no new Docker service):
    0 7 * * * docker compose -f /path/to/open-brain/docker-compose.yml run --rm worker python -m src.jobs.pulse
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

_PULSE_QUESTION_SYSTEM_PROMPT = """You generate the daily question for a personal morning check-in system.

Generate ONE question. Alternate between two types across days:

TYPE A — Operational nudge (practical, about tasks/projects):
"You've deferred X three times — what's actually blocking it?"
"You have a call with someone at 14:00 — what outcome do you want?"

TYPE B — Reflective question (deeper, wellness/growth oriented):
"What's one thing you're avoiding that would make today better?"
"What gave you energy yesterday vs what drained it?"
"If today went perfectly, what would be different by evening?"

Rules:
- Max 20 words
- Be direct, no fluff
- Alternate types: if yesterday was Type A, today should be Type B (and vice versa)
- Output only the question text, nothing else. No quotes, no labels."""


async def _generate_ai_question(
    llm: Any,
    open_todos: list[dict[str, Any]] | None = None,
    yesterday_question: str | None = None,
) -> str:
    """Generate a contextual morning question via Haiku. Falls back to a default on failure."""
    default_question = "What's one thing you want to accomplish today?"
    if llm is None:
        return default_question

    context_parts: list[str] = []
    if open_todos:
        todo_lines = [f"- {t.get('description', '')[:80]}" for t in open_todos[:5]]
        context_parts.append("Open todos:\n" + "\n".join(todo_lines))
    if yesterday_question:
        context_parts.append(f"Yesterday's question: {yesterday_question}")
        context_parts.append(
            "If yesterday's question was operational, generate reflective today, and vice versa."
        )
    else:
        context_parts.append("No yesterday question — default to Type B (reflective).")

    context_block = "\n\n".join(context_parts) if context_parts else "No context available."
    user_content = f"Context:\n{context_block}\n\nGenerate today's morning check-in question."

    try:
        question = await llm.complete(
            system_prompt=_PULSE_QUESTION_SYSTEM_PROMPT,
            user_content=user_content,
            max_tokens=80,
        )
        cleaned = question.strip().strip('"').strip("'")
        if cleaned and not cleaned.endswith("?"):
            cleaned = cleaned.rstrip("?") + "?"
        return cleaned or default_question
    except Exception as exc:
        logger.exception("pulse_question_generation_failed", error=str(exc))
        return default_question


# ── Main job helpers ───────────────────────────────────────────────────────────


async def _pulse_already_sent_today(http: httpx.AsyncClient, settings: Any) -> bool:
    """Return True if a pulse record already exists for today (idempotency check)."""
    try:
        resp = await http.get(
            f"{settings.open_brain_api_url}/v1/pulse/today",
            headers={"X-API-Key": settings.api_key.get_secret_value()},
        )
        if resp.status_code == 200:
            existing = resp.json()
            logger.info(
                "pulse_already_sent_today",
                status=existing.get("status"),
                pulse_id=existing.get("id"),
            )
            return True
        return False
    except httpx.RequestError as exc:
        logger.error("pulse_idempotency_check_failed", error=str(exc))
        return True  # fail-safe: don't send on error


# ── Main job: trigger_morning_pulse ───────────────────────────────────────────


async def _start_pulse_via_api(
    http: httpx.AsyncClient, settings: Any
) -> dict[str, Any] | None:
    """POST /v1/pulse/start — runs the signal pipeline (or legacy) in-process.

    Returns the created pulse dict, or None on HTTP failure.
    """
    try:
        resp = await http.post(
            f"{settings.open_brain_api_url}/v1/pulse/start",
            headers={"X-API-Key": settings.api_key.get_secret_value()},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        logger.exception("pulse_start_via_api_failed", error=str(exc))
        return None


async def trigger_morning_pulse(http: httpx.AsyncClient) -> None:
    """Trigger the morning pulse pipeline. Idempotent — exits early if already sent today.

    Calls POST /v1/pulse/start which runs the signal-driven pipeline and creates
    today's pulse record. The web dashboard surfaces the result.
    """
    settings = _get_settings()

    if await _pulse_already_sent_today(http, settings):
        return

    pulse = await _start_pulse_via_api(http, settings)
    if pulse is None:
        return

    logger.info(
        "pulse_triggered",
        pulse_id=pulse.get("id"),
        status=pulse.get("status"),
    )


# ── Settings helper ────────────────────────────────────────────────────────────


def _get_settings() -> Any:
    from src.core import config

    if config.settings is None:
        config.settings = config.Settings()
    return config.settings


# ── Entry point ────────────────────────────────────────────────────────────────


async def _pulse_job() -> None:
    """Core pulse job logic (no DB init — handled by runner)."""
    async with httpx.AsyncClient(timeout=30.0) as http:
        await trigger_morning_pulse(http)


async def _main() -> None:
    """CLI entry point for cron invocation."""
    from src.jobs.runner import run_tracked

    await run_tracked("pulse", _pulse_job)


if __name__ == "__main__":
    asyncio.run(_main())
