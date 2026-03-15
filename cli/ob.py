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
from datetime import datetime, timedelta, timezone
from typing import Annotated

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
        dt = dt.replace(tzinfo=timezone.utc)
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
    window_start = datetime.now(timezone.utc) - timedelta(hours=24)

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
    typer.echo(f"\n--- {ctx.items_included} items, {ctx.tokens_used}/{ctx.tokens_budget} tokens ---")


# ── ob worker ─────────────────────────────────────────────────────────────────


@app.command()
def worker(
    sync: Annotated[
        bool,
        typer.Option("--sync", help="Process one batch and exit (default: continuous polling loop)"),
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
        typer.echo(
            "Error: Anthropic or Voyage API key not configured in environment.", err=True
        )
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


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    """Entry point for the `ob` CLI command (registered in pyproject.toml)."""
    app()
