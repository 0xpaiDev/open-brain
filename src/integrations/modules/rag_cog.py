"""Discord RAG Chat module for Open Brain.

Handles '?'-prefixed messages in whitelisted channels:
  → hybrid search for context
  → Claude LLM with conversation history
  → cited Discord reply

Conversation state is DB-persisted in rag_conversations (survives bot restarts).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import discord
import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db_context as get_db
from src.core.models import RagConversation
from src.integrations.kernel import _get_settings, ingest_memory, search_memories

logger = structlog.get_logger(__name__)

_RATE_LIMIT_SECONDS = 10


# ── Pure helpers (no I/O, fully testable) ─────────────────────────────────────


def _parse_model_override(content: str, settings: Any) -> tuple[str, str]:
    """Parse model override token from message content.

    Strips the trigger prefix, then checks if the first word is a known model token.

    Supported tokens:
      ?sonnet <query>  → (rag_sonnet_model, query)
      ?haiku <query>   → (rag_default_model, query)
      ? <query>        → (rag_default_model, query)
      ?<query>         → (rag_default_model, query)
      ?unknown <query> → (rag_default_model, 'unknown <query>')  — token not stripped

    Returns:
        (model_id, cleaned_query)
    """
    prefix: str = settings.rag_trigger_prefix
    without_prefix = content[len(prefix):]

    known_tokens = {
        "sonnet": settings.rag_sonnet_model,
        "haiku": settings.rag_default_model,
    }

    lower = without_prefix.lower()
    for token, model_id in known_tokens.items():
        if lower == token:
            return model_id, ""
        if lower.startswith(token + " "):
            return model_id, without_prefix[len(token) :].strip()

    return settings.rag_default_model, without_prefix.lstrip()


def _build_system_prompt(context: str) -> str:
    """Build the RAG system prompt with memory context.

    Context is wrapped in XML tags for prompt injection defense.
    """
    if context.strip():
        return (
            "You are a knowledgeable assistant with access to the user's personal memory system. "
            "Answer questions using the provided memory context when relevant. "
            "Be concise and accurate. If the context doesn't contain relevant information, "
            "say so honestly — do not invent or extrapolate. "
            "Always respond in English, regardless of the language of the memory context.\n\n"
            f"Memory context:\n<context>\n{context}\n</context>"
        )
    return (
        "You are a knowledgeable assistant. "
        "No relevant memories were found for this query. "
        "Answer honestly based on what you know, or tell the user you don't have that information. "
        "Always respond in English."
    )


def _build_rag_user_message(query: str) -> str:
    """Wrap user query in XML tags for prompt injection defense."""
    return f"<user_input>{query}</user_input>"


def _trim_buffer(messages: list[dict[str, str]], buffer_size: int) -> list[dict[str, str]]:
    """Trim conversation buffer to the last buffer_size user+assistant pairs.

    Drops oldest pairs from the front. Always trims in multiples of 2 to maintain
    user/assistant alternation.

    Args:
        messages: Flat list alternating user/assistant messages
        buffer_size: Max number of pairs to retain

    Returns:
        Trimmed list with at most buffer_size * 2 messages
    """
    max_messages = buffer_size * 2
    if len(messages) <= max_messages:
        return messages
    return messages[-max_messages:]


def _is_conversation_expired(last_active_at: datetime, ttl_hours: int) -> bool:
    """Return True if last_active_at is older than ttl_hours ago.

    Args:
        last_active_at: Timestamp of last conversation activity
        ttl_hours: TTL threshold in hours

    Returns:
        True if the conversation has expired, False otherwise
    """
    now = datetime.now(tz=timezone.utc)
    if last_active_at.tzinfo is None:
        last_active_at = last_active_at.replace(tzinfo=timezone.utc)
    return (now - last_active_at).total_seconds() > ttl_hours * 3600


def _format_citations(results: list[dict[str, Any]]) -> str:
    """Format search results as a compact citations footer string."""
    lines = []
    for i, r in enumerate(results[:3], start=1):
        snippet = (r.get("content") or "")[:120].replace("\n", " ")
        rtype = r.get("type", "memory")
        lines.append(f"{i}. [{rtype}] {snippet}…")
    return "\n".join(lines)


# ── Database helpers ───────────────────────────────────────────────────────────


async def _load_or_create_conversation(
    session: AsyncSession,
    channel_id: str,
    user_id: str,
    settings: Any,
) -> RagConversation:
    """Fetch or create a RagConversation for this (channel, user) pair.

    If an existing conversation is found but has exceeded the TTL, its messages
    are reset to [] and model_name reverts to the default.

    Args:
        session: Active async DB session
        channel_id: Discord channel ID (as string)
        user_id: Discord user ID (as string)
        settings: Application settings

    Returns:
        RagConversation ORM object (may be freshly created or loaded)
    """
    stmt = select(RagConversation).where(
        (RagConversation.discord_channel_id == channel_id)
        & (RagConversation.discord_user_id == user_id)
    )
    conv: RagConversation | None = (await session.execute(stmt)).scalar_one_or_none()

    if conv is None:
        conv = RagConversation(
            discord_channel_id=channel_id,
            discord_user_id=user_id,
            messages=[],
            model_name=settings.rag_default_model,
        )
        session.add(conv)
        await session.flush()
        await session.refresh(conv)
        return conv

    # TTL expiry check: reset stale conversations
    if conv.last_active_at is not None and _is_conversation_expired(
        conv.last_active_at, settings.rag_conversation_ttl_hours
    ):
        conv.messages = []
        conv.model_name = settings.rag_default_model
        await session.flush()

    return conv


# ── Main RAG pipeline ──────────────────────────────────────────────────────────


async def _handle_rag_message(
    message: discord.Message,
    http: httpx.AsyncClient,
    settings: Any,
    anthropic: Any,  # AnthropicClient — typed as Any to avoid circular import
) -> None:
    """Execute the full RAG pipeline for a single ?-prefixed message.

    Pipeline:
      1. Load/create conversation (DB) — apply TTL reset if expired
      2. Rate limit check (10s between turns)
      3. Parse model override from message content
      4. Search memories via /v1/search
      5. Build system prompt + user message with context (XML-wrapped)
      6. Call Claude with conversation history
      7. Trim buffer to rag_conversation_buffer_size pairs
      8. Save conversation (flush + commit + refresh)
      9. Reply with answer; send citations embed if results found
      10. Optionally ingest Q+A as memory (rag_save_qa_as_memory)

    Args:
        message: Discord Message object triggering the RAG query
        http: httpx.AsyncClient for API calls
        settings: Application settings
        anthropic: AnthropicClient instance with complete_with_history()
    """
    channel_id = str(message.channel.id)
    user_id = str(message.author.id)
    log = logger.bind(channel_id=channel_id, user_id=user_id)

    try:
        async with get_db() as session:
            conv = await _load_or_create_conversation(session, channel_id, user_id, settings)

            # ── Rate limit: only if conversation already has history ──────────
            if conv.messages:
                now = datetime.now(tz=timezone.utc)
                last_active = conv.last_active_at
                if last_active is not None:
                    if last_active.tzinfo is None:
                        last_active = last_active.replace(tzinfo=timezone.utc)
                    elapsed = (now - last_active).total_seconds()
                    if elapsed < _RATE_LIMIT_SECONDS:
                        await message.reply(
                            "Please wait a moment before asking again.",
                            mention_author=False,
                        )
                        return

            # ── Parse model override ──────────────────────────────────────────
            model_id, query = _parse_model_override(message.content, settings)
            if not query.strip():
                await message.reply(
                    f"Please provide a question after `{settings.rag_trigger_prefix}`.",
                    mention_author=False,
                )
                return

            # Use model stored in conversation unless this message overrides it
            # Model switch: if user explicitly typed ?sonnet or ?haiku, update stored model
            effective_model = model_id
            if effective_model != conv.model_name:
                log.info("rag_model_switch", from_model=conv.model_name, to_model=effective_model)

            # ── Search memories ───────────────────────────────────────────────
            results: list[dict[str, Any]] = []
            try:
                results = await search_memories(
                    http,
                    query=query,
                    limit=5,
                    api_key=settings.api_key.get_secret_value(),
                    api_base_url=settings.open_brain_api_url,
                )
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                log.warning("rag_search_failed", error=str(exc))
                # Continue with empty context — LLM will say it has no info

            # ── Build context and prompt ──────────────────────────────────────
            context_parts = [r.get("content", "") for r in results if r.get("content")]
            context = "\n\n".join(context_parts)
            system_prompt = _build_system_prompt(context)
            user_msg_content = _build_rag_user_message(query)

            # ── Build messages list: history + current turn ───────────────────
            history: list[dict[str, str]] = list(conv.messages)
            messages_for_llm = [*history, {"role": "user", "content": user_msg_content}]

            # ── Call Claude ───────────────────────────────────────────────────
            response_text = await anthropic.complete_with_history(
                system_prompt=system_prompt,
                messages=messages_for_llm,
                model=effective_model,
                max_tokens=1024,
            )

            # ── Update conversation buffer ────────────────────────────────────
            # Store raw query in history (not XML-wrapped) for clean replay
            new_history = [
                *history,
                {"role": "user", "content": query},
                {"role": "assistant", "content": response_text},
            ]
            new_history = _trim_buffer(new_history, settings.rag_conversation_buffer_size)

            conv.messages = new_history
            conv.model_name = effective_model
            conv.last_active_at = datetime.now(tz=timezone.utc)
            await session.flush()
            await session.commit()
            await session.refresh(conv)

            log.info(
                "rag_response_generated",
                model=effective_model,
                results_count=len(results),
                history_len=len(new_history),
            )

        # ── Discord reply (outside session) ──────────────────────────────────
        await message.reply(response_text, mention_author=False)

        # Citations embed (up to 3 results)
        if results:
            embed = discord.Embed(title="Sources", color=discord.Color.blurple())
            for r in results[:3]:
                snippet = (r.get("content") or "")[:150].replace("\n", " ")
                field_name = r.get("type", "memory")
                embed.add_field(name=field_name, value=snippet, inline=False)
            await message.channel.send(embed=embed)

        # Optionally ingest Q+A as memory
        if settings.rag_save_qa_as_memory and query.strip():
            qa_text = f"Q: {query}\nA: {response_text}"
            try:
                await ingest_memory(
                    http,
                    raw_text=qa_text,
                    author_id=user_id,
                    channel_id=channel_id,
                    api_key=settings.api_key.get_secret_value(),
                    api_base_url=settings.open_brain_api_url,
                )
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                log.warning("rag_ingest_qa_failed", error=str(exc))

    except Exception as exc:
        log.exception("rag_pipeline_error", error=str(exc))
        try:
            await message.reply(
                "Something went wrong processing your query. Please try again.",
                mention_author=False,
            )
        except Exception:
            pass


# ── Registration ───────────────────────────────────────────────────────────────

# Module-level singleton set by register_rag — referenced by discord_bot.py guard
_rag_handler: Any | None = None


def register_rag(
    bot: discord.Client,
    http: httpx.AsyncClient,
    settings: Any,
) -> None:
    """Register the RAG message handler.

    Creates a single AnthropicClient instance shared across all RAG interactions.
    Sets _rag_handler so discord_bot.py's on_message can route prefixed messages to it.

    Args:
        bot: The OpenBrainBot instance (discord.Client)
        http: Shared httpx.AsyncClient for API calls
        settings: Application settings (must have anthropic_api_key)
    """
    global _rag_handler
    from src.llm.client import AnthropicClient

    if not settings.anthropic_api_key:
        logger.warning("rag_disabled_no_anthropic_key")
        return

    api_key_value = settings.anthropic_api_key.get_secret_value()
    if not api_key_value.strip():
        logger.warning("rag_disabled_empty_anthropic_key")
        return

    anthropic = AnthropicClient(api_key=api_key_value, model=settings.rag_default_model)

    async def on_rag_message(message: discord.Message) -> None:
        """Gate on channel, user, and prefix before dispatching."""
        if message.author.bot:
            return
        if message.channel.id not in settings.discord_rag_channel_ids:
            return
        if message.author.id not in settings.discord_allowed_user_ids:
            return
        if not message.content.startswith(settings.rag_trigger_prefix):
            return

        await asyncio.ensure_future(_handle_rag_message(message, http, settings, anthropic))

    _rag_handler = on_rag_message
    logger.info(
        "rag_listener_registered",
        channel_ids=settings.discord_rag_channel_ids,
        default_model=settings.rag_default_model,
    )
