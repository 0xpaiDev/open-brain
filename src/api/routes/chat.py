"""Chat endpoint.

POST /v1/chat — multi-turn RAG chat with query formulation and synthesis.

Pipeline:
  1. Validate model against allowlist
  2. Formulate search query via Haiku (fallback: raw message)
  3. Embed formulated query via Voyage AI
  4. Hybrid search over memory_items
  5. Build token-budgeted context from results
  6. Build system prompt with memory + optional external context
  7. Wrap user messages in <user_input> tags (prompt injection defense)
  8. Synthesize response via Claude (user-selected model)
  9. Commit session (retrieval event persistence)
  10. Return response with sources and metadata
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import chat_limit, limiter
from src.core.database import get_db
from src.llm.client import AnthropicClient, ExtractionFailed, VoyageEmbeddingClient
from src.llm.rag_prompts import (
    QUERY_FORMULATION_SYSTEM,
    build_query_formulation_content,
    build_rag_system_prompt,
    build_rag_user_message,
)
from src.retrieval.context_builder import build_context
from src.retrieval.search import SearchResult, hybrid_search

logger = structlog.get_logger(__name__)

router = APIRouter()

_MAX_EXTERNAL_CONTEXT = 20_000
_MAX_HISTORY_MESSAGES = 20


# ── Pydantic models ─────────────────────────────────────────────────────────


class ChatMessage(BaseModel):
    """A single message in the conversation history."""

    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1, max_length=50_000)


class ChatRequest(BaseModel):
    """Request body for POST /v1/chat."""

    message: str = Field(..., min_length=1, max_length=10_000)
    history: list[ChatMessage] = Field(default_factory=list)
    model: str | None = None
    external_context: str | None = Field(default=None, max_length=_MAX_EXTERNAL_CONTEXT)


class ChatSourceItem(BaseModel):
    """A source memory item referenced during synthesis."""

    id: str
    content: str
    summary: str | None
    type: str
    importance_score: float
    combined_score: float
    project: str | None = None


class ChatResponse(BaseModel):
    """Response body for POST /v1/chat."""

    response: str
    sources: list[ChatSourceItem]
    model: str
    search_query: str


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_settings():
    """Lazy settings accessor — avoids module-level import capture."""
    from src.core import config as _config

    if _config.settings is None:
        _config.settings = _config.Settings()
    return _config.settings


# ── Endpoint ─────────────────────────────────────────────────────────────────


@router.post("/v1/chat", response_model=ChatResponse)
@limiter.limit(chat_limit)
async def chat(
    request: Request,
    body: ChatRequest,
    session: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Multi-turn RAG chat with query formulation and synthesis.

    Reformulates the user message into an optimised search query (via Haiku),
    retrieves relevant memories via hybrid search, and synthesises a response
    using the user-selected model with full conversation history.

    Raises:
        422: Invalid model, history too long, or invalid message format.
        500: Synthesis or embedding failure.
    """
    settings = _get_settings()

    # ── 1. Validate ──────────────────────────────────────────────────────────
    if len(body.history) > _MAX_HISTORY_MESSAGES:
        raise HTTPException(
            status_code=422,
            detail=f"History must not exceed {_MAX_HISTORY_MESSAGES} messages",
        )

    allowed_models = {settings.rag_default_model, settings.rag_sonnet_model}
    resolved_model = body.model or settings.rag_default_model
    if resolved_model not in allowed_models:
        raise HTTPException(
            status_code=422,
            detail=f"Model must be one of: {', '.join(sorted(allowed_models))}",
        )

    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="Chat service unavailable (no LLM key)")

    # ── 2. Create Anthropic client (haiku for formulation) ───────────────────
    anthropic = AnthropicClient(
        api_key=settings.anthropic_api_key.get_secret_value(),
        model=settings.rag_default_model,
    )

    # ── 3. Formulate search query ────────────────────────────────────────────
    history_dicts = [{"role": m.role, "content": m.content} for m in body.history]
    formulation_content = build_query_formulation_content(
        history=history_dicts,
        external_context=body.external_context,
        user_message=body.message,
    )

    try:
        search_query = await anthropic.complete(
            system_prompt=QUERY_FORMULATION_SYSTEM,
            user_content=formulation_content,
            max_tokens=200,
        )
        search_query = search_query.strip()
        if not search_query:
            search_query = body.message
    except ExtractionFailed:
        logger.warning("chat_query_formulation_failed", fallback="raw_message")
        search_query = body.message

    # ── 4. Embed the formulated query ────────────────────────────────────────
    voyage = VoyageEmbeddingClient(
        api_key=settings.voyage_api_key.get_secret_value() if settings.voyage_api_key else "",
        model=settings.voyage_model,
    )
    query_embedding = await voyage.embed(search_query)

    # ── 5. Hybrid search ─────────────────────────────────────────────────────
    results: list[SearchResult] = await hybrid_search(
        session=session,
        query_text=search_query,
        query_embedding=query_embedding,
        limit=10,
    )

    # ── 6. Build context ─────────────────────────────────────────────────────
    ctx = build_context(results)

    # ── 7. Build system prompt ───────────────────────────────────────────────
    full_context = ctx.context
    if body.external_context:
        ext = body.external_context[:_MAX_EXTERNAL_CONTEXT]
        if full_context:
            full_context = f"{full_context}\n\nAdditional context:\n{ext}"
        else:
            full_context = ext
    system_prompt = build_rag_system_prompt(full_context)

    # ── 8. Build messages — wrap user input in <user_input> tags ─────────────
    messages_for_llm: list[dict[str, str]] = []
    for m in body.history:
        if m.role == "user":
            messages_for_llm.append({"role": "user", "content": build_rag_user_message(m.content)})
        else:
            messages_for_llm.append({"role": m.role, "content": m.content})
    messages_for_llm.append({"role": "user", "content": build_rag_user_message(body.message)})

    # ── 9. Synthesize ────────────────────────────────────────────────────────
    response_text = await anthropic.complete_with_history(
        system_prompt=system_prompt,
        messages=messages_for_llm,
        model=resolved_model,
        max_tokens=2048,
    )

    # ── 10. Commit + respond ─────────────────────────────────────────────────
    await session.commit()

    sources = [
        ChatSourceItem(
            id=r.id,
            content=r.content,
            summary=r.summary,
            type=r.type,
            importance_score=r.importance_score,
            combined_score=r.combined_score,
            project=r.project,
        )
        for r in results
    ]

    logger.info(
        "chat_request",
        search_query=search_query,
        model=resolved_model,
        sources_count=len(sources),
        history_len=len(body.history),
    )

    return ChatResponse(
        response=response_text,
        sources=sources,
        model=resolved_model,
        search_query=search_query,
    )
