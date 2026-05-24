"""Low-level recording helpers.

All functions are no-ops when called outside an active start_trace() context,
so instrumented library code doesn't break tests that don't open a trace.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import structlog

from src.llm.pricing import PRICING_VERSION, compute_cost_usd
from src.observability.context import _current_trace, _short_id

log = structlog.get_logger(__name__)


def _now() -> datetime:
    return datetime.now(tz=UTC)


async def record_llm_call(
    *,
    call_site: str,
    model: str,
    status: str,
    usage: object | None = None,
    raw_request: dict | None = None,
    raw_response: dict | None = None,
    request_summary: dict | None = None,
    response_summary: dict | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    error_message: str | None = None,
    error_class: str | None = None,
    stop_reason: str | None = None,
    parent_span_id: str | None = None,
    provider: str = "anthropic",
) -> None:
    """Write one LLMCall row. No-op outside a trace."""
    from src.core.models import LLMCall

    ctx = _current_trace.get()
    if ctx is None:
        return

    now = _now()
    fa = finished_at or now
    sa = started_at or now
    duration_ms = int((fa - sa).total_seconds() * 1000) if started_at else None

    cost_usd = compute_cost_usd(model, usage) if usage is not None else None
    input_tokens = getattr(usage, "input_tokens", None) if usage else None
    output_tokens = getattr(usage, "output_tokens", None) if usage else None
    cache_read = getattr(usage, "cache_read_input_tokens", None) if usage else None
    cache_write = getattr(usage, "cache_creation_input_tokens", None) if usage else None

    row = LLMCall(
        id=uuid4(),
        trace_id=ctx.trace_id,
        span_id=_short_id(),
        parent_span_id=parent_span_id or ctx.current_span_id(),
        call_site=call_site,
        model=model,
        provider=provider,
        status=status,
        started_at=sa,
        finished_at=fa,
        duration_ms=duration_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
        stop_reason=stop_reason,
        cost_usd=float(cost_usd) if cost_usd is not None else 0.0,
        pricing_version=PRICING_VERSION,
        raw_request=raw_request,
        raw_response=raw_response,
        request_summary=request_summary or {},
        response_summary=response_summary,
        error_message=error_message,
        error_class=error_class,
    )
    ctx.session.add(row)
    await ctx.session.flush()

    _update_trace_totals(
        ctx,
        cost_usd=float(cost_usd) if cost_usd is not None else 0.0,
        input_tokens=input_tokens or 0,
        output_tokens=output_tokens or 0,
        cache_read=cache_read or 0,
        cache_write=cache_write or 0,
        llm_call_delta=1,
    )


def _update_trace_totals(
    ctx: object,
    *,
    cost_usd: float = 0.0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read: int = 0,
    cache_write: int = 0,
    llm_call_delta: int = 0,
    tool_call_delta: int = 0,
) -> None:
    """Accumulate running totals on the TraceContext for rollup at close."""
    if not hasattr(ctx, "_totals"):
        ctx._totals = {  # type: ignore[attr-defined]
            "cost_usd": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read": 0,
            "cache_write": 0,
            "llm_call_count": 0,
            "tool_call_count": 0,
        }
    t = ctx._totals  # type: ignore[attr-defined]
    t["cost_usd"] += cost_usd
    t["input_tokens"] += input_tokens
    t["output_tokens"] += output_tokens
    t["cache_read"] += cache_read
    t["cache_write"] += cache_write
    t["llm_call_count"] += llm_call_delta
    t["tool_call_count"] += tool_call_delta


async def record_tool_call(
    *,
    tool_name: str,
    args: dict,
    status: str,
    result: dict | None = None,
    is_error: bool = False,
    error_message: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    parent_span_id: str | None = None,
) -> None:
    """Write one ToolCall row. No-op outside a trace."""
    from src.core.models import ToolCall

    ctx = _current_trace.get()
    if ctx is None:
        return

    now = _now()
    fa = finished_at or now
    sa = started_at or now
    duration_ms = int((fa - sa).total_seconds() * 1000) if started_at else None

    row = ToolCall(
        id=uuid4(),
        trace_id=ctx.trace_id,
        span_id=_short_id(),
        parent_span_id=parent_span_id or ctx.current_span_id(),
        tool_name=tool_name,
        status=status,
        started_at=sa,
        finished_at=fa,
        duration_ms=duration_ms,
        args=args,
        result=result,
        is_error=is_error,
        error_message=error_message,
    )
    ctx.session.add(row)
    await ctx.session.flush()

    _update_trace_totals(ctx, tool_call_delta=1)


async def record_event(
    *,
    event_type: str,
    payload: dict | None = None,
    level: str = "info",
    parent_span_id: str | None = None,
) -> None:
    """Write one untyped Event row. No-op outside a trace."""
    from src.core.models import ObsEvent

    ctx = _current_trace.get()
    if ctx is None:
        return

    row = ObsEvent(
        id=uuid4(),
        trace_id=ctx.trace_id,
        span_id=_short_id(),
        parent_span_id=parent_span_id or ctx.current_span_id(),
        event_type=event_type,
        level=level,
        payload=payload,
    )
    ctx.session.add(row)
    await ctx.session.flush()
