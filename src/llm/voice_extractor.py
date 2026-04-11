"""Haiku field extraction for the voice command endpoint.

Each extractor wraps `anthropic_client.complete` in an outer
`asyncio.wait_for` with a tight timeout (default 1.5s) so one LLM call
cannot blow the < 2s Siri latency budget. The shared client's internal
timeout is 60s which is far too loose for this call path.

Design notes:
- The classifier (src/api/services/voice_intent.py) has already locked in
  an intent before we get here — these extractors only pull structured
  fields out of an already-known shape.
- Malformed JSON, timeouts, and API errors all raise `VoiceExtractionFailed`.
  Callers decide the fallback: create path falls back to raw dictation,
  complete path converts to an ambiguous no-op response.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import date

import structlog

from src.core.config import get_settings
from src.llm.client import ExtractionFailed
from src.llm.prompts import (
    VOICE_COMPLETE_SYSTEM_PROMPT,
    VOICE_CREATE_SYSTEM_PROMPT,
    build_voice_extraction_message,
)

logger = structlog.get_logger(__name__)


class VoiceExtractionFailed(Exception):
    """Raised when Haiku fails to return a parseable JSON object in budget."""


@dataclass
class CreateFields:
    description: str
    due_date: date | None


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_MAX_TOKENS = 256


def _parse_json_object(raw: str) -> dict:
    """Extract the first JSON object from a string, tolerantly."""
    match = _JSON_OBJECT_RE.search(raw)
    if not match:
        raise VoiceExtractionFailed(f"no JSON object in response: {raw!r}")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise VoiceExtractionFailed(f"invalid JSON: {exc}") from exc


def _parse_due_date(value: object) -> date | None:
    if value in (None, "", "null"):
        return None
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


async def _complete_within_budget(system_prompt: str, user_content: str) -> str:
    """Call anthropic_client.complete wrapped in the voice-command timeout."""
    from src.llm.client import anthropic_client  # deferred for test monkeypatching

    if anthropic_client is None:
        raise VoiceExtractionFailed("anthropic_client is not configured")

    timeout = get_settings().voice_command_llm_timeout_seconds
    try:
        return await asyncio.wait_for(
            anthropic_client.complete(
                system_prompt=system_prompt,
                user_content=user_content,
                max_tokens=_MAX_TOKENS,
            ),
            timeout=timeout,
        )
    except TimeoutError as exc:
        logger.warning("voice_extractor_timeout", timeout=timeout)
        raise VoiceExtractionFailed(
            f"voice extractor exceeded {timeout}s budget"
        ) from exc
    except ExtractionFailed as exc:
        logger.warning("voice_extractor_llm_error", error=str(exc))
        raise VoiceExtractionFailed(str(exc)) from exc


async def extract_create_fields(text: str) -> CreateFields:
    """Extract {description, due_date} for a create-todo intent.

    Raises:
        VoiceExtractionFailed: on timeout, API error, malformed JSON, or
            a missing/empty description. Callers should fall back to the
            raw dictation as the description.
    """
    user_content = build_voice_extraction_message(text)
    raw = await _complete_within_budget(VOICE_CREATE_SYSTEM_PROMPT, user_content)
    payload = _parse_json_object(raw)

    description = payload.get("description")
    if not isinstance(description, str) or not description.strip():
        raise VoiceExtractionFailed("description missing from Haiku response")

    return CreateFields(
        description=description.strip(),
        due_date=_parse_due_date(payload.get("due_date")),
    )


async def extract_complete_target(text: str) -> str:
    """Extract the target phrase for a complete-todo intent.

    Raises:
        VoiceExtractionFailed: on timeout, API error, malformed JSON, or
            a missing/empty target_phrase. Callers should convert this to
            an ambiguous (no-op) response — never fall through to memory.
    """
    user_content = build_voice_extraction_message(text)
    raw = await _complete_within_budget(VOICE_COMPLETE_SYSTEM_PROMPT, user_content)
    payload = _parse_json_object(raw)

    target = payload.get("target_phrase")
    if not isinstance(target, str) or not target.strip():
        raise VoiceExtractionFailed("target_phrase missing from Haiku response")
    return target.strip()
