"""POST /v1/voice/command — unified iOS Shortcut dictation endpoint.

Routes a single dictated string into one of three intents (create todo,
complete todo, save memory) based on deterministic keyword routing, then
uses Haiku only for structured field extraction inside the locked intent.

Design constraints:
- End-to-end latency < 2s (Siri attention span). The classifier + fuzzy
  matcher stay in the low-millisecond range; only the Haiku extraction
  step can approach the budget, and it's capped at ~1.5s.
- Every mutating path (created / completed) returns a human-readable
  `message` that names the exact todo title so the iOS Shortcut can
  surface it as a notification and the user notices bad mis-classifications.
- Ambiguous completion is a HARD no-op: no TodoHistory row, no RawMemory
  insert, no partial write. It returns 200 with `action="ambiguous"`.
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

# Reuse `memory_limit` deliberately — the voice endpoint shares the Back-Tap
# capture envelope with /v1/memory. Introducing a new `voice_command_limit`
# setting would add a config knob with no operational benefit today.
from src.api.middleware.rate_limit import limiter, memory_limit
from src.api.services.memory_service import ingest_memory
from src.api.services.todo_service import create_todo, update_todo
from src.api.services.voice_intent import (
    MATCH_CONFIDENCE_THRESHOLD,
    classify_intent,
    match_open_todo,
)
from src.core.database import get_db
from src.llm.voice_extractor import (
    VoiceExtractionFailed,
    extract_complete_target,
    extract_create_fields,
)

logger = structlog.get_logger(__name__)

router = APIRouter()

_MAX_METADATA_BYTES = 8192


# ── Schemas ──────────────────────────────────────────────────────────────────


class VoiceCommandRequest(BaseModel):
    """Request body for POST /v1/voice/command."""

    text: str = Field(..., min_length=1, max_length=5000)
    source: str = Field("voice", max_length=50)
    metadata: dict[str, Any] | None = None

    @field_validator("metadata")
    @classmethod
    def _validate_metadata_size(
        cls, v: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if v is None:
            return v
        serialized = json.dumps(v, separators=(",", ":"))
        if len(serialized.encode()) > _MAX_METADATA_BYTES:
            raise ValueError(
                f"metadata exceeds maximum allowed size of {_MAX_METADATA_BYTES} bytes"
            )
        return v


class VoiceCommandResponse(BaseModel):
    """Response body for POST /v1/voice/command."""

    action: Literal["created", "completed", "memory", "ambiguous"]
    entity_id: str | None = None
    title: str | None = None
    confidence: float
    message: str


# ── Route ────────────────────────────────────────────────────────────────────


@router.post("/v1/voice/command", response_model=VoiceCommandResponse)
@limiter.limit(memory_limit)
async def voice_command_route(
    request: Request,
    body: VoiceCommandRequest,
    session: AsyncSession = Depends(get_db),
) -> Any:
    """Dispatch dictated text into create / complete / memory / ambiguous.

    Status codes:
        200 — action in {"created", "completed", "ambiguous"}
        202 — action == "memory" (matches /v1/memory contract)
    """
    intent = classify_intent(body.text)
    logger.info("voice_command_intent", intent=intent, length=len(body.text))

    if intent == "create":
        return await _handle_create(session, body)
    if intent == "complete":
        return await _handle_complete(session, body)
    return await _handle_memory(session, body)


# ── Handlers ─────────────────────────────────────────────────────────────────


async def _handle_create(
    session: AsyncSession,
    body: VoiceCommandRequest,
) -> VoiceCommandResponse:
    """Extract fields via Haiku; on timeout/parse fail, fall back to raw dictation."""
    description: str
    due_date: _dt.datetime | None = None

    try:
        fields = await extract_create_fields(body.text)
        description = fields.description
        if fields.due_date is not None:
            due_date = _dt.datetime.combine(
                fields.due_date, _dt.time.min, tzinfo=_dt.UTC
            )
    except VoiceExtractionFailed as exc:
        logger.warning("voice_create_extract_failed_fallback", error=str(exc))
        description = body.text.strip()

    todo = await create_todo(session, description=description, due_date=due_date)
    logger.info("voice_command_created", todo_id=str(todo.id))
    return VoiceCommandResponse(
        action="created",
        entity_id=str(todo.id),
        title=todo.description,
        confidence=1.0,
        message=f'Added todo: "{todo.description}"',
    )


async def _handle_complete(
    session: AsyncSession,
    body: VoiceCommandRequest,
) -> VoiceCommandResponse:
    """Extract target phrase, fuzzy-match, and either complete or no-op."""
    try:
        target = await extract_complete_target(body.text)
    except VoiceExtractionFailed as exc:
        logger.warning("voice_complete_extract_failed", error=str(exc))
        return _ambiguous_response(body.text, confidence=0.0)

    todo, score = await match_open_todo(session, target)
    if todo is None or score < MATCH_CONFIDENCE_THRESHOLD:
        logger.info("voice_complete_ambiguous", score=score, target=target)
        return _ambiguous_response(body.text, confidence=score)

    reason = f"voice: {body.text} (match_score={score:.2f})"
    updated = await update_todo(
        session,
        todo,
        status="done",
        reason=reason,
        fields_set={"status", "reason"},
    )
    logger.info("voice_command_completed", todo_id=str(updated.id), score=score)
    return VoiceCommandResponse(
        action="completed",
        entity_id=str(updated.id),
        title=updated.description,
        confidence=score,
        message=f'Completed: "{updated.description}"',
    )


async def _handle_memory(
    session: AsyncSession,
    body: VoiceCommandRequest,
) -> JSONResponse:
    """Ingest dictation as a raw memory (status 202 to match /v1/memory)."""
    result = await ingest_memory(
        session,
        text=body.text,
        source=body.source,
        metadata=body.metadata,
    )
    logger.info("voice_command_memory", raw_id=result.raw_id, status=result.status)
    payload = VoiceCommandResponse(
        action="memory",
        entity_id=result.raw_id,
        title=None,
        confidence=1.0,
        message="Saved to memory.",
    )
    return JSONResponse(status_code=202, content=payload.model_dump())


def _ambiguous_response(text: str, *, confidence: float) -> VoiceCommandResponse:
    return VoiceCommandResponse(
        action="ambiguous",
        entity_id=None,
        title=None,
        confidence=confidence,
        message=f'No confident match for "{text}". Nothing was changed.',
    )
