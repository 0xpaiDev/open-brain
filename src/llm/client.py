"""LLM and embedding clients for Open Brain.

This module wraps the Anthropic and Voyage AI SDKs with structured error handling.
Named exceptions (ExtractionFailed, EmbeddingFailed) allow callers to distinguish
between transient and permanent failures.

Module-level singletons are created lazily if API keys are present in settings.
For tests, mock instances can be injected directly.
"""

import asyncio
import hashlib
from datetime import UTC, datetime

import structlog
from anthropic import Anthropic, APIError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
)
from voyageai import Client as VoyageClient

from src.core.config import get_settings
from src.observability.recording import record_llm_call

logger = structlog.get_logger(__name__)

_LLM_TIMEOUT_SECONDS = 60.0
_EMBED_TIMEOUT_SECONDS = 30.0


# ── Exceptions ────────────────────────────────────────────────────────────


class ExtractionFailed(Exception):
    """Raised when LLM extraction fails after all retries or on schema mismatch."""

    pass


class EmbeddingFailed(Exception):
    """Raised when Voyage AI embedding fails after all retries."""

    pass


# ── Anthropic Client ──────────────────────────────────────────────────────


class AnthropicClient:
    """Async wrapper around the Anthropic SDK."""

    def __init__(self, api_key: str, model: str) -> None:
        """Initialize with API key and model name.

        Args:
            api_key: Anthropic API key (will be stored in client but not logged)
            model: Model name (e.g., 'claude-haiku-4-5-20251001')
        """
        self.client = Anthropic(api_key=api_key)
        self.model = model
        logger.info(
            "anthropic_client_initialized",
            model=model,
        )

    async def complete(
        self,
        system_prompt: str,
        user_content: str,
        max_tokens: int = 1024,
    ) -> str:
        """Call Claude Haiku to get a completion.

        Args:
            system_prompt: System prompt guiding Claude's behavior
            user_content: User message content
            max_tokens: Max tokens in response (default 1024)

        Returns:
            Raw text response from Claude

        Raises:
            ExtractionFailed: If the API call fails
        """
        started_at = datetime.now(UTC)
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.messages.create,
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_content}],
                ),
                timeout=_LLM_TIMEOUT_SECONDS,
            )
            if not response.content:
                raise ExtractionFailed("Anthropic returned empty content array")
            text = response.content[0].text
            finished_at = datetime.now(UTC)
            logger.debug(
                "anthropic_complete_success",
                model=self.model,
                response_len=len(text),
            )
            await record_llm_call(
                call_site="llm.complete",
                model=self.model,
                status="success",
                usage=response.usage,
                raw_request={
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_content}],
                    "tools": [],
                    "model": self.model,
                    "max_tokens": max_tokens,
                },
                raw_response=response.model_dump(),
                request_summary={
                    "system_prompt_hash": hashlib.sha256(system_prompt.encode()).hexdigest()[:8],
                    "message_count": 1,
                    "tool_count": 0,
                    "max_tokens": max_tokens,
                },
                response_summary={
                    "output_text_truncated": text[:200],
                    "tool_use_count": 0,
                    "content_block_types": ["text"],
                    "stop_reason": response.stop_reason,
                },
                started_at=started_at,
                finished_at=finished_at,
                stop_reason=response.stop_reason,
            )
            return text
        except TimeoutError:
            logger.exception("anthropic_timeout", model=self.model, timeout=_LLM_TIMEOUT_SECONDS)
            await record_llm_call(
                call_site="llm.complete",
                model=self.model,
                status="failed",
                error_message=f"Anthropic API timed out after {_LLM_TIMEOUT_SECONDS}s",
                error_class="TimeoutError",
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
            raise ExtractionFailed(
                f"Anthropic API timed out after {_LLM_TIMEOUT_SECONDS}s"
            ) from None
        except APIError as e:
            logger.exception("anthropic_api_error", error=str(e))
            await record_llm_call(
                call_site="llm.complete",
                model=self.model,
                status="failed",
                error_message=str(e),
                error_class=type(e).__name__,
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
            raise ExtractionFailed(f"Anthropic API error: {e}") from e
        except Exception as e:
            logger.exception("anthropic_unexpected_error", error=str(e))
            await record_llm_call(
                call_site="llm.complete",
                model=self.model,
                status="failed",
                error_message=str(e),
                error_class=type(e).__name__,
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
            raise ExtractionFailed(f"Unexpected error calling Anthropic: {e}") from e

    async def _messages_create(
        self,
        *,
        messages: list[dict],
        system: str,
        tools: list[dict],
        model: str,
        max_tokens: int = 2048,
    ):
        """Raw messages.create call used by the tool-use loop.

        Does not modify complete_with_history — this is a separate path that
        supports tool schemas and returns the raw Message object.
        """
        def _call():
            return self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                tools=tools if tools else [],
            )

        started_at = datetime.now(UTC)
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(_call),
                timeout=_LLM_TIMEOUT_SECONDS,
            )
            finished_at = datetime.now(UTC)
            await record_llm_call(
                call_site="llm.messages_create",
                model=model,
                status="success",
                usage=response.usage,
                raw_request={
                    "system": system,
                    "messages": messages,
                    "tools": tools,
                    "model": model,
                    "max_tokens": max_tokens,
                },
                raw_response=response.model_dump(),
                request_summary={
                    "system_prompt_hash": hashlib.sha256(system.encode()).hexdigest()[:8],
                    "message_count": len(messages),
                    "tool_count": len(tools),
                    "max_tokens": max_tokens,
                },
                response_summary={
                    "output_text_truncated": next(
                        (b.text for b in response.content if b.type == "text"), ""
                    )[:200],
                    "tool_use_count": sum(1 for b in response.content if b.type == "tool_use"),
                    "content_block_types": list({b.type for b in response.content}),
                    "stop_reason": response.stop_reason,
                },
                started_at=started_at,
                finished_at=finished_at,
                stop_reason=response.stop_reason,
            )
            return response
        except TimeoutError as exc:
            logger.error("_messages_create_timeout", model=model)
            await record_llm_call(
                call_site="llm.messages_create",
                model=model,
                status="failed",
                error_message="LLM tool-use call timed out",
                error_class="TimeoutError",
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
            raise ExtractionFailed("LLM tool-use call timed out") from exc
        except APIError as exc:
            logger.error("_messages_create_api_error", status=exc.status_code)
            await record_llm_call(
                call_site="llm.messages_create",
                model=model,
                status="failed",
                error_message=f"Anthropic API error: {exc.status_code}",
                error_class=type(exc).__name__,
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
            raise ExtractionFailed(f"Anthropic API error: {exc.status_code}") from exc
        except Exception as exc:
            logger.error("_messages_create_error", error=str(exc))
            await record_llm_call(
                call_site="llm.messages_create",
                model=model,
                status="failed",
                error_message=str(exc),
                error_class=type(exc).__name__,
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
            raise ExtractionFailed(f"Unexpected LLM error: {exc}") from exc

    async def complete_with_history(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        model: str | None = None,
        max_tokens: int = 1024,
    ) -> str:
        """Call Claude with a multi-turn message history.

        Args:
            system_prompt: System prompt (injected memory context goes here)
            messages: Full conversation [{role: "user"|"assistant", content: "..."}]
            model: Model override; falls back to self.model if None
            max_tokens: Max tokens in response

        Returns:
            Raw text response from Claude

        Raises:
            ExtractionFailed: If the API call fails
        """
        resolved_model = model or self.model
        started_at = datetime.now(UTC)
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.messages.create,
                    model=resolved_model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=messages,
                ),
                timeout=_LLM_TIMEOUT_SECONDS,
            )
            if not response.content:
                raise ExtractionFailed("Anthropic returned empty content array")
            text = response.content[0].text
            finished_at = datetime.now(UTC)
            logger.debug(
                "anthropic_complete_with_history_success",
                model=resolved_model,
                response_len=len(text),
                history_len=len(messages),
            )
            await record_llm_call(
                call_site="llm.complete_with_history",
                model=resolved_model,
                status="success",
                usage=response.usage,
                raw_request={
                    "system": system_prompt,
                    "messages": messages,
                    "tools": [],
                    "model": resolved_model,
                    "max_tokens": max_tokens,
                },
                raw_response=response.model_dump(),
                request_summary={
                    "system_prompt_hash": hashlib.sha256(system_prompt.encode()).hexdigest()[:8],
                    "message_count": len(messages),
                    "tool_count": 0,
                    "max_tokens": max_tokens,
                },
                response_summary={
                    "output_text_truncated": text[:200],
                    "tool_use_count": 0,
                    "content_block_types": ["text"],
                    "stop_reason": response.stop_reason,
                },
                started_at=started_at,
                finished_at=finished_at,
                stop_reason=response.stop_reason,
            )
            return text
        except TimeoutError:
            logger.exception(
                "anthropic_timeout", model=resolved_model, timeout=_LLM_TIMEOUT_SECONDS
            )
            await record_llm_call(
                call_site="llm.complete_with_history",
                model=resolved_model,
                status="failed",
                error_message=f"Anthropic API timed out after {_LLM_TIMEOUT_SECONDS}s",
                error_class="TimeoutError",
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
            raise ExtractionFailed(
                f"Anthropic API timed out after {_LLM_TIMEOUT_SECONDS}s"
            ) from None
        except APIError as e:
            logger.exception("anthropic_api_error", error=str(e))
            await record_llm_call(
                call_site="llm.complete_with_history",
                model=resolved_model,
                status="failed",
                error_message=str(e),
                error_class=type(e).__name__,
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
            raise ExtractionFailed(f"Anthropic API error: {e}") from e
        except Exception as e:
            logger.exception("anthropic_unexpected_error", error=str(e))
            await record_llm_call(
                call_site="llm.complete_with_history",
                model=resolved_model,
                status="failed",
                error_message=str(e),
                error_class=type(e).__name__,
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
            raise ExtractionFailed(f"Unexpected error calling Anthropic: {e}") from e


# ── Voyage AI Embedding Client ────────────────────────────────────────────


class VoyageEmbeddingClient:
    """Async wrapper around Voyage AI embedding client.

    Note: voyageai.Client.embed() is synchronous. We wrap it in asyncio.to_thread()
    to avoid blocking the event loop. Tenacity retries are applied at the method level.
    """

    def __init__(self, api_key: str, model: str) -> None:
        """Initialize with API key and model name.

        Args:
            api_key: Voyage AI API key
            model: Model name (e.g., 'voyage-3')
        """
        self.client = VoyageClient(api_key=api_key)
        self.model = model
        logger.info(
            "voyage_client_initialized",
            model=model,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        reraise=True,
    )
    async def embed(self, text: str) -> list[float]:
        """Embed text using Voyage AI.

        The sync voyageai.Client.embed() is wrapped in asyncio.to_thread() to avoid
        blocking the event loop. Tenacity will retry up to 3 times with exponential
        backoff (2–8 seconds between attempts).

        Args:
            text: Text to embed

        Returns:
            List of 1024 float values (embedding vector)

        Raises:
            EmbeddingFailed: If all 3 retry attempts fail
        """
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.embed,
                    [text],
                    model=self.model,
                ),
                timeout=_EMBED_TIMEOUT_SECONDS,
            )
            if not result.embeddings:
                raise EmbeddingFailed("Voyage AI returned empty embeddings array")
            embedding = result.embeddings[0]
            logger.debug(
                "voyage_embed_success",
                model=self.model,
                text_len=len(text),
                embedding_dims=len(embedding),
            )
            return embedding
        except TimeoutError:
            logger.exception(
                "voyage_embed_timeout", model=self.model, timeout=_EMBED_TIMEOUT_SECONDS
            )
            raise EmbeddingFailed(
                f"Voyage AI embedding timed out after {_EMBED_TIMEOUT_SECONDS}s"
            ) from None
        except Exception as e:
            logger.exception(
                "voyage_embed_error",
                model=self.model,
                error=str(e),
            )
            raise EmbeddingFailed(f"Voyage AI embedding failed: {e}") from e


# ── Module-level singletons ───────────────────────────────────────────────


def _create_anthropic_client() -> AnthropicClient | None:
    """Create Anthropic client if API key is present."""
    s = get_settings()
    if s.anthropic_api_key and s.anthropic_api_key.get_secret_value().strip():
        try:
            return AnthropicClient(
                api_key=s.anthropic_api_key.get_secret_value(),
                model=s.anthropic_model,
            )
        except Exception as e:
            logger.exception("failed_to_create_anthropic_client", error=str(e))
            return None
    return None


def _create_voyage_client() -> VoyageEmbeddingClient | None:
    """Create Voyage AI client if API key is present."""
    s = get_settings()
    if s.voyage_api_key and s.voyage_api_key.get_secret_value().strip():
        try:
            return VoyageEmbeddingClient(
                api_key=s.voyage_api_key.get_secret_value(),
                model=s.voyage_model,
            )
        except Exception as e:
            logger.exception("failed_to_create_voyage_client", error=str(e))
            return None
    return None


# Lazy singleton instances — initialized on first import if keys are present
anthropic_client: AnthropicClient | None = _create_anthropic_client()
embedding_client: VoyageEmbeddingClient | None = _create_voyage_client()
