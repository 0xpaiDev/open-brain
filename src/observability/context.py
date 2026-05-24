"""Trace / span lifecycle context managers.

Observability uses its own dedicated DB session (via get_db_context) so that
trace data is committed independently of the business-logic session. This means
failure traces survive even when the caller's session is rolled back.

Usage:
    async with start_trace(trigger_type="cron", trigger_name="synthesis") as ctx:
        async with start_step("load_inputs"):
            ...
        async with start_step("run_llm"):
            ...
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import structlog
import structlog.contextvars
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _short_id() -> str:
    return hashlib.sha1(os.urandom(8)).hexdigest()[:12]


@dataclass
class SpanContext:
    span_id: str
    parent_span_id: str | None
    started_at: datetime


@dataclass
class TraceContext:
    trace_id: str
    span_id: str
    session: AsyncSession
    started_at: datetime
    _span_stack: list[SpanContext] = field(default_factory=list)

    def current_span_id(self) -> str:
        return self._span_stack[-1].span_id if self._span_stack else self.span_id

    def current_parent_span_id(self) -> str | None:
        if len(self._span_stack) > 1:
            return self._span_stack[-2].span_id
        return self.span_id if self._span_stack else None


_current_trace: ContextVar[TraceContext | None] = ContextVar("_current_trace", default=None)


def current_trace() -> TraceContext | None:
    return _current_trace.get()


def current_trace_id() -> str | None:
    ctx = _current_trace.get()
    return str(ctx.trace_id) if ctx else None


def current_span_id() -> str | None:
    ctx = _current_trace.get()
    return ctx.current_span_id() if ctx else None


@asynccontextmanager
async def start_trace(
    *,
    trigger_type: str,
    trigger_name: str | None = None,
    trigger_metadata: dict | None = None,
    causal_parent_trace_id: str | None = None,
) -> AsyncGenerator[TraceContext, None]:
    """Open a new root trace. Commits independently of the caller's session.

    No-ops gracefully when the observability DB session is unavailable
    (e.g. in unit tests that do not initialise the DB engine). In that case
    the body still executes; trace recording is simply skipped.
    """
    from src.core import database as _db_mod
    from src.core.database import get_db_context
    from src.core.models import Trace

    if _db_mod.AsyncSessionLocal is None:
        # DB not initialised — run the body without recording.
        yield TraceContext(
            trace_id=str(uuid4()),
            span_id=_short_id(),
            session=None,  # type: ignore[arg-type]
            started_at=_now(),
        )
        return

    trace_id = uuid4()
    span_id = _short_id()
    started_at = _now()

    async with get_db_context() as session:
        trace_row = Trace(
            id=trace_id,
            trigger_type=trigger_type,
            trigger_name=trigger_name,
            trigger_metadata=trigger_metadata,
            causal_parent_trace_id=causal_parent_trace_id,
            status="running",
            started_at=started_at,
        )
        session.add(trace_row)
        await session.flush()

        ctx = TraceContext(
            trace_id=trace_id,
            span_id=span_id,
            session=session,
            started_at=started_at,
        )
        token = _current_trace.set(ctx)
        structlog.contextvars.bind_contextvars(trace_id=str(trace_id), span_id=span_id)

        status = "success"
        error_msg = None
        error_cls = None
        try:
            yield ctx
        except Exception as exc:
            status = "failed"
            error_msg = str(exc)
            error_cls = type(exc).__name__
            raise
        finally:
            finished_at = _now()
            duration_ms = int((finished_at - started_at).total_seconds() * 1000)

            await session.refresh(trace_row)
            trace_row.status = status
            trace_row.finished_at = finished_at
            trace_row.duration_ms = duration_ms
            trace_row.error_message = error_msg
            trace_row.error_class = error_cls

            totals = getattr(ctx, "_totals", {})
            if totals:
                trace_row.total_cost_usd = totals.get("cost_usd")
                trace_row.total_input_tokens = totals.get("input_tokens")
                trace_row.total_output_tokens = totals.get("output_tokens")
                trace_row.total_cache_read_tokens = totals.get("cache_read")
                trace_row.total_cache_creation_tokens = totals.get("cache_write")
                trace_row.llm_call_count = totals.get("llm_call_count")
                trace_row.tool_call_count = totals.get("tool_call_count")

            await session.commit()

            _current_trace.reset(token)
            structlog.contextvars.unbind_contextvars("trace_id", "span_id")


@asynccontextmanager
async def start_step(step_name: str, metadata: dict | None = None) -> AsyncGenerator[None, None]:
    """Open a named CronStep span within the current trace. No-op if no trace active."""
    from src.core.models import CronStep

    ctx = _current_trace.get()
    if ctx is None:
        yield
        return

    span_id = _short_id()
    parent_span_id = ctx.current_span_id()
    started_at = _now()

    span = SpanContext(span_id=span_id, parent_span_id=parent_span_id, started_at=started_at)
    ctx._span_stack.append(span)
    structlog.contextvars.bind_contextvars(span_id=span_id)

    step_row = CronStep(
        id=uuid4(),
        trace_id=ctx.trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        step_name=step_name,
        status="running",
        started_at=started_at,
        step_metadata=metadata,
    )
    ctx.session.add(step_row)
    await ctx.session.flush()

    status = "success"
    error_msg = None
    error_cls = None
    try:
        yield
    except Exception as exc:
        status = "failed"
        error_msg = str(exc)
        error_cls = type(exc).__name__
        raise
    finally:
        finished_at = _now()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)

        await ctx.session.refresh(step_row)
        step_row.status = status
        step_row.finished_at = finished_at
        step_row.duration_ms = duration_ms
        step_row.error_message = error_msg
        step_row.error_class = error_cls
        await ctx.session.flush()

        ctx._span_stack.pop()
        parent_sid = ctx.current_span_id()
        structlog.contextvars.bind_contextvars(span_id=parent_sid)
