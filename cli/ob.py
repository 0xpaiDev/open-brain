"""Open Brain CLI — memory ingestion, search, and worker control.

Each command is a thin sync wrapper around an async helper so that typer's
CliRunner works correctly in tests (CliRunner is synchronous; asyncio.run()
bridges the gap). External calls (DB, LLM APIs) are always mocked in tests
by patching the async helper functions (e.g., _ingest_async).

Entry point registered in pyproject.toml:
    ob = "cli.ob:main"
"""

import asyncio
import hashlib
import os
from datetime import UTC, datetime, timedelta
from typing import Annotated

import httpx
import structlog
import typer
from sqlalchemy import select

logger = structlog.get_logger(__name__)

app = typer.Typer(name="ob", help="Open Brain CLI — memory ingestion, search, and worker control.")


# ── Shared helpers ────────────────────────────────────────────────────────────


def _get_settings():
    """Return the settings singleton, instantiating it on-demand if needed."""
    from src.core import config

    if config.settings is None:
        config.settings = config.Settings()
    return config.settings


def _make_voyage_client():
    """Instantiate a VoyageEmbeddingClient using current settings."""
    from src.llm.client import VoyageEmbeddingClient

    s = _get_settings()
    return VoyageEmbeddingClient(
        api_key=s.voyage_api_key.get_secret_value() if s.voyage_api_key else "",
        model=s.voyage_model,
    )


def _content_hash(text: str) -> str:
    """SHA-256 hash of normalized text (lowercase + collapsed whitespace)."""
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()


def _parse_date(s: str | None) -> datetime | None:
    """Parse an ISO 8601 date string; attach UTC if naive. Returns None for None input."""
    if s is None:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


# ── ob ingest ─────────────────────────────────────────────────────────────────


@app.command()
def ingest(
    text: Annotated[str, typer.Argument(help="Text to ingest into memory")],
    source: Annotated[str, typer.Option("--source", help="Source label (default: cli)")] = "cli",
) -> None:
    """Ingest text into raw_memory and enqueue for pipeline processing.

    Applies the same 24-hour content-hash deduplication as the POST /v1/memory
    endpoint. If a duplicate is found within the window, reports the existing
    raw_id and exits without creating new rows.
    """
    asyncio.run(_ingest_async(text, source))


async def _ingest_async(text: str, source: str) -> None:
    from src.core.database import get_db_context, init_db
    from src.core.models import RawMemory, RefinementQueue

    await init_db()

    content_hash = _content_hash(text)
    window_start = datetime.now(UTC) - timedelta(hours=24)

    async with get_db_context() as session:
        result = await session.execute(
            select(RawMemory)
            .where(RawMemory.content_hash == content_hash)
            .where(RawMemory.created_at >= window_start)
            .limit(1)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            typer.echo(f"Duplicate detected. raw_id={existing.id} status=duplicate")
            logger.info("cli_ingest_duplicate", raw_id=str(existing.id), content_hash=content_hash)
            return

        raw = RawMemory(source=source, raw_text=text, content_hash=content_hash)
        session.add(raw)
        await session.flush()

        queue_entry = RefinementQueue(raw_id=raw.id)
        session.add(queue_entry)
        await session.flush()
        await session.commit()

    typer.echo(f"Ingested. raw_id={raw.id} status=queued")
    logger.info("cli_ingest_success", raw_id=str(raw.id), source=source)


# ── ob search ─────────────────────────────────────────────────────────────────


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search query text")],
    limit: Annotated[int, typer.Option("--limit", help="Maximum results to return")] = 10,
    type_filter: Annotated[
        str | None, typer.Option("--type", help="Filter by type: memory, decision, task")
    ] = None,
    entity: Annotated[
        str | None, typer.Option("--entity", help="Filter by entity name or alias")
    ] = None,
    date_from: Annotated[
        str | None, typer.Option("--from", help="Earliest date (ISO 8601, e.g. 2026-01-01)")
    ] = None,
    date_to: Annotated[
        str | None, typer.Option("--to", help="Latest date (ISO 8601, e.g. 2026-12-31)")
    ] = None,
) -> None:
    """Search memory items using hybrid vector + keyword search.

    Embeds the query via Voyage AI, runs hybrid search (pgvector + GIN FTS),
    applies combined scoring, and pretty-prints ranked results.
    """
    try:
        date_from_dt = _parse_date(date_from)
        date_to_dt = _parse_date(date_to)
    except ValueError as e:
        typer.echo(f"Error: invalid date — {e}", err=True)
        raise typer.Exit(code=1) from e

    asyncio.run(_search_async(query, limit, type_filter, entity, date_from_dt, date_to_dt))


async def _search_async(
    query: str,
    limit: int,
    type_filter: str | None,
    entity_filter: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> None:
    from src.core.database import get_db_context, init_db
    from src.retrieval.search import hybrid_search

    await init_db()
    voyage = _make_voyage_client()
    query_embedding = await voyage.embed(query)

    async with get_db_context() as session:
        results = await hybrid_search(
            session=session,
            query_text=query,
            query_embedding=query_embedding,
            limit=limit,
            type_filter=type_filter,
            entity_filter=entity_filter,
            date_from=date_from,
            date_to=date_to,
        )
        await session.commit()

    if not results:
        typer.echo("No results found.")
        return

    for i, r in enumerate(results, 1):
        date_str = r.created_at.strftime("%Y-%m-%d") if r.created_at else "unknown"
        typer.echo(f"[{i}] {r.type.upper()} | {date_str} | score={r.combined_score:.3f}")
        typer.echo(f"    {r.content[:120]}{'...' if len(r.content) > 120 else ''}")
        if r.summary:
            typer.echo(f"    Summary: {r.summary}")
        typer.echo("")


# ── ob context ────────────────────────────────────────────────────────────────


@app.command()
def context(
    query: Annotated[str, typer.Argument(help="Search query text")],
    limit: Annotated[
        int, typer.Option("--limit", help="Maximum results to search before building context")
    ] = 10,
) -> None:
    """Build and print an LLM-ready context string from hybrid search results.

    Embeds the query, runs hybrid search, formats ranked results into a
    token-budgeted context string suitable for injection into an LLM prompt.
    """
    asyncio.run(_context_async(query, limit))


async def _context_async(query: str, limit: int) -> None:
    from src.core.database import get_db_context, init_db
    from src.retrieval.context_builder import build_context
    from src.retrieval.search import hybrid_search

    await init_db()
    voyage = _make_voyage_client()
    query_embedding = await voyage.embed(query)

    async with get_db_context() as session:
        results = await hybrid_search(
            session=session,
            query_text=query,
            query_embedding=query_embedding,
            limit=limit,
        )
        await session.commit()

    ctx = build_context(results)
    typer.echo(ctx.context)
    typer.echo(
        f"\n--- {ctx.items_included} items, {ctx.tokens_used}/{ctx.tokens_budget} tokens ---"
    )


# ── ob worker ─────────────────────────────────────────────────────────────────


@app.command()
def worker(
    sync: Annotated[
        bool,
        typer.Option(
            "--sync", help="Process one batch and exit (default: continuous polling loop)"
        ),
    ] = False,
) -> None:
    """Run the pipeline worker.

    Without --sync: starts the continuous polling loop (blocks until SIGTERM).
    With --sync: claims one batch, processes it, then exits. Useful for
    one-shot invocations (e.g., cron jobs, tests).
    """
    asyncio.run(_worker_async(sync))


async def _worker_async(sync: bool) -> None:
    from src.core.database import get_db_context, init_db
    from src.llm.client import anthropic_client, embedding_client
    from src.pipeline.worker import claim_batch, process_job, run

    await init_db()

    if not sync:
        # Delegate to the full polling loop (installs SIGTERM handler)
        await run()
        return

    # --sync: claim one batch and process it, then exit
    if anthropic_client is None or embedding_client is None:
        typer.echo("Error: Anthropic or Voyage API key not configured in environment.", err=True)
        raise typer.Exit(code=1)

    async with get_db_context() as session:
        jobs = await claim_batch(session, batch_size=1)
        await session.commit()

    if not jobs:
        typer.echo("No pending jobs.")
        return

    for job in jobs:
        await process_job(job, anthropic_client, embedding_client)

    typer.echo(f"Processed {len(jobs)} job(s).")
    logger.info("cli_worker_sync_done", jobs_processed=len(jobs))


# ── ob health ─────────────────────────────────────────────────────────────────


@app.command()
def health() -> None:
    """Check database connectivity and print status."""
    asyncio.run(_health_async())


async def _health_async() -> None:
    from src.core.database import health_check, init_db

    await init_db()
    ok = await health_check()
    if ok:
        typer.echo("status=ok database=reachable")
    else:
        typer.echo("status=error database=unreachable", err=True)
        raise typer.Exit(code=1)


# ── ob chat ───────────────────────────────────────────────────────────────────

_SUPPORTED_MODELS = ("claude", "gemini", "openai")

# Open Brain API coordinates for chat (reads env, falls back to local defaults)
_OB_API_URL: str = os.environ.get("OPENBRAIN_API_URL", "http://localhost:8000").rstrip("/")
_OB_API_KEY: str = os.environ.get("OPENBRAIN_API_KEY", "")
_OB_TIMEOUT: float = 30.0


def _fetch_ob_context(query: str) -> str:
    """Fetch LLM-ready context from the Open Brain API.

    Returns an empty string on any error so the chat loop degrades gracefully.
    """
    try:
        resp = httpx.get(
            f"{_OB_API_URL}/v1/search/context",
            params={"q": query, "limit": 10},
            headers={"X-API-Key": _OB_API_KEY},
            timeout=_OB_TIMEOUT,
        )
        if resp.status_code == 200:
            return resp.json().get("context", "")
    except Exception:
        pass
    return ""


async def _call_claude(system: str, messages: list[dict[str, str]]) -> str:
    """Call Claude Haiku and return reply text."""
    from anthropic import Anthropic

    api_key_env = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key_env:
        s = _get_settings()
        api_key_env = s.anthropic_api_key.get_secret_value() if s.anthropic_api_key else ""
    if not api_key_env:
        typer.echo("Error: ANTHROPIC_API_KEY not set.", err=True)
        raise typer.Exit(code=1)
    client = Anthropic(api_key=api_key_env)
    response = await asyncio.to_thread(
        lambda: client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=system,
            messages=messages,  # type: ignore[arg-type]
        )
    )
    # First content block is always TextBlock for non-tool calls
    return str(response.content[0].text)  # type: ignore[union-attr]


async def _call_gemini(system: str, messages: list[dict[str, str]]) -> str:
    """Call Gemini Flash and return reply text."""
    try:
        from google import genai  # type: ignore[import-not-found]
        from google.genai import types  # type: ignore[import-not-found]
    except ImportError as exc:
        typer.echo("Error: google-genai not installed. Run: pip install google-genai", err=True)
        raise typer.Exit(code=1) from exc
    api_key_env = os.environ.get("GEMINI_API_KEY", "")
    if not api_key_env:
        typer.echo("Error: GEMINI_API_KEY not set.", err=True)
        raise typer.Exit(code=1)
    client = genai.Client(api_key=api_key_env)
    history = [
        types.Content(role=m["role"], parts=[types.Part(text=m["content"])])
        for m in messages[:-1]
    ]
    chat_session = client.chats.create(
        model="gemini-2.0-flash",
        config=types.GenerateContentConfig(system_instruction=system),
        history=history,
    )
    result = await asyncio.to_thread(chat_session.send_message, messages[-1]["content"])
    return str(result.text)


async def _call_openai(system: str, messages: list[dict[str, str]]) -> str:
    """Call GPT-4o-mini and return reply text."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        typer.echo("Error: openai not installed. Run: pip install openai", err=True)
        raise typer.Exit(code=1) from exc
    api_key_env = os.environ.get("OPENAI_API_KEY", "")
    if not api_key_env:
        typer.echo("Error: OPENAI_API_KEY not set.", err=True)
        raise typer.Exit(code=1)
    client = OpenAI(api_key=api_key_env)
    all_messages = [{"role": "system", "content": system}] + messages
    response = await asyncio.to_thread(
        client.chat.completions.create,
        model="gpt-4o-mini",
        messages=all_messages,
        max_tokens=2048,
    )
    return response.choices[0].message.content or ""


async def _call_llm_for_chat(model: str, system: str, messages: list[dict[str, str]]) -> str:
    """Dispatch to the correct LLM backend.

    Raises:
        typer.Exit: if model is unknown or API keys are missing.
        Exception: propagated from the LLM SDK on API error.
    """
    if model == "claude":
        return await _call_claude(system, messages)
    if model == "gemini":
        return await _call_gemini(system, messages)
    if model == "openai":
        return await _call_openai(system, messages)
    typer.echo(
        f"Error: unknown model '{model}'. Choose from: {', '.join(_SUPPORTED_MODELS)}", err=True
    )
    raise typer.Exit(code=1)


def _post_to_ob(text: str, source: str) -> None:
    """Post text to Open Brain for async pipeline ingestion. Silently ignores errors."""
    try:
        httpx.post(
            f"{_OB_API_URL}/v1/memory",
            json={"text": text, "source": source},
            headers={"X-API-Key": _OB_API_KEY, "Content-Type": "application/json"},
            timeout=_OB_TIMEOUT,
        )
    except Exception:
        pass


@app.command()
def chat(
    model: Annotated[
        str, typer.Option("--model", help=f"LLM to use: {', '.join(_SUPPORTED_MODELS)}")
    ] = "claude",
    topic: Annotated[
        str | None, typer.Option("--topic", help="Seed topic for initial memory search")
    ] = None,
    no_ingest: Annotated[
        bool, typer.Option("--no-ingest", help="Skip ingesting the conversation at session end")
    ] = False,
) -> None:
    """Start an interactive chat session grounded in your Open Brain memory.

    On each turn the CLI fetches relevant context from Open Brain and injects
    it into the LLM system prompt. At session end the conversation is ingested
    back into Open Brain (use --no-ingest to skip).

    Supported models: claude (default), gemini, openai.
    """
    if model not in _SUPPORTED_MODELS:
        typer.echo(
            f"Error: unknown model '{model}'. Choose from: {', '.join(_SUPPORTED_MODELS)}",
            err=True,
        )
        raise typer.Exit(code=1)
    asyncio.run(_chat_async(model, topic, no_ingest))


async def _chat_async(model: str, topic: str | None, no_ingest: bool) -> None:
    """Core chat loop: context retrieval → LLM call → optional ingestion."""
    conversation: list[dict[str, str]] = []

    typer.echo(f"Open Brain Chat [{model}] — type 'exit' or Ctrl+C to quit.\n")

    # Seed context from --topic before first user message
    seed_context = _fetch_ob_context(topic) if topic else ""
    base_system = (
        "You are an AI assistant with access to the user's personal memory system (Open Brain). "
        "Use the context below to give informed, personalised responses. "
        "If the context is empty, answer from your general knowledge.\n"
    )

    try:
        while True:
            try:
                user_input = input("You: ").strip()
            except EOFError:
                break

            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit"):
                break

            # Refresh context on each turn using the user's message
            turn_context = _fetch_ob_context(user_input)
            context_block = turn_context or seed_context

            system_prompt = base_system
            if context_block:
                system_prompt += f"\n## Relevant Memory Context\n\n{context_block}"

            conversation.append({"role": "user", "content": user_input})

            try:
                reply = await _call_llm_for_chat(model, system_prompt, conversation)
            except typer.Exit:
                raise
            except Exception as e:
                typer.echo(f"\nLLM error: {e}\n", err=True)
                conversation.pop()  # remove the failed user message
                continue

            typer.echo(f"\nAssistant: {reply}\n")
            conversation.append({"role": "assistant", "content": reply})

    except KeyboardInterrupt:
        pass

    if not no_ingest and conversation:
        turns = "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in conversation)
        full_text = f"[ob chat session — model={model}]\n\n{turns}"
        _post_to_ob(full_text, source="ob-chat")
        typer.echo("\nConversation ingested into Open Brain.")


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    """Entry point for the `ob` CLI command (registered in pyproject.toml)."""
    app()
