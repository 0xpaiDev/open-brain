"""Observability API routes.

GET  /v1/traces/kpis                     — KPI tiles (cost today, sparkline, cache-hit-rate, failures, dead letters)
GET  /v1/traces                          — paginated list with filters
GET  /v1/traces/{trace_id}               — full trace detail (child spans via selectinload)
POST /v1/traces/{trace_id}/rerun         — rerun a trace; {"new_trace_id": "..."}
POST /v1/spans/{span_table}/{span_id}/replay — replay one LLM call span; {"new_span_id": "...", "status": "..."}
"""

from __future__ import annotations

import asyncio
import uuid as _uuid
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.middleware.rate_limit import limiter
from src.core.database import get_db
from src.core.models import CronStep, LLMCall, ObsEvent, ToolCall, Trace
from src.llm.pricing import PRICING_VERSION, compute_cost_usd
from src.observability.context import _short_id

log = structlog.get_logger(__name__)
router = APIRouter()


# ── Helpers ────────────────────────────────────────────────────────────────────


def _fmt_cost(v: object) -> str | None:
    if v is None:
        return None
    return f"{float(v):.6f}"


def _to_utc_ts(dt: datetime) -> float:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC).timestamp()
    return dt.timestamp()


def _trace_to_list_item(t: Trace) -> dict:
    return {
        "id": str(t.id),
        "trigger_type": t.trigger_type,
        "trigger_name": t.trigger_name,
        "status": t.status,
        "started_at": t.started_at.isoformat(),
        "finished_at": t.finished_at.isoformat() if t.finished_at else None,
        "duration_ms": t.duration_ms,
        "total_cost_usd": _fmt_cost(t.total_cost_usd),
        "total_input_tokens": t.total_input_tokens,
        "total_output_tokens": t.total_output_tokens,
        "total_cache_read_tokens": t.total_cache_read_tokens,
        "total_cache_creation_tokens": t.total_cache_creation_tokens,
        "llm_call_count": t.llm_call_count,
        "tool_call_count": t.tool_call_count,
        "error_message": t.error_message,
        "error_class": t.error_class,
        "causal_parent_trace_id": str(t.causal_parent_trace_id) if t.causal_parent_trace_id else None,
        "rerun_of_trace_id": str(t.rerun_of_trace_id) if t.rerun_of_trace_id else None,
    }


def _trace_to_detail(t: Trace) -> dict:
    d = _trace_to_list_item(t)
    d["trigger_metadata"] = t.trigger_metadata
    d["cron_steps"] = [_cron_step_to_dict(cs) for cs in t.cron_steps]
    d["llm_calls"] = [_llm_call_to_dict(lc) for lc in t.llm_call_spans]
    d["tool_calls"] = [_tool_call_to_dict(tc) for tc in t.tool_call_spans]
    d["events"] = [_event_to_dict(e) for e in t.event_spans]
    return d


def _cron_step_to_dict(cs: CronStep) -> dict:
    return {
        "id": str(cs.id),
        "span_id": cs.span_id,
        "parent_span_id": cs.parent_span_id,
        "step_name": cs.step_name,
        "status": cs.status,
        "started_at": cs.started_at.isoformat() if cs.started_at else None,
        "finished_at": cs.finished_at.isoformat() if cs.finished_at else None,
        "duration_ms": cs.duration_ms,
        "error_message": cs.error_message,
        "error_class": cs.error_class,
        "step_metadata": cs.step_metadata,
    }


def _llm_call_to_dict(lc: LLMCall) -> dict:
    return {
        "id": str(lc.id),
        "span_id": lc.span_id,
        "parent_span_id": lc.parent_span_id,
        "call_site": lc.call_site,
        "model": lc.model,
        "provider": lc.provider,
        "status": lc.status,
        "started_at": lc.started_at.isoformat() if lc.started_at else None,
        "finished_at": lc.finished_at.isoformat() if lc.finished_at else None,
        "duration_ms": lc.duration_ms,
        "input_tokens": lc.input_tokens,
        "output_tokens": lc.output_tokens,
        "cache_read_input_tokens": lc.cache_read_input_tokens,
        "cache_creation_input_tokens": lc.cache_creation_input_tokens,
        "stop_reason": lc.stop_reason,
        "cost_usd": _fmt_cost(lc.cost_usd),
        "pricing_version": lc.pricing_version,
        "request_summary": lc.request_summary,
        "response_summary": lc.response_summary,
        "error_message": lc.error_message,
        "error_class": lc.error_class,
    }


def _tool_call_to_dict(tc: ToolCall) -> dict:
    return {
        "id": str(tc.id),
        "span_id": tc.span_id,
        "parent_span_id": tc.parent_span_id,
        "tool_name": tc.tool_name,
        "status": tc.status,
        "started_at": tc.started_at.isoformat() if tc.started_at else None,
        "finished_at": tc.finished_at.isoformat() if tc.finished_at else None,
        "duration_ms": tc.duration_ms,
        "args": tc.args,
        "result": tc.result,
        "is_error": tc.is_error,
        "error_message": tc.error_message,
    }


def _event_to_dict(e: ObsEvent) -> dict:
    return {
        "id": str(e.id),
        "span_id": e.span_id,
        "parent_span_id": e.parent_span_id,
        "event_type": e.event_type,
        "level": e.level,
        "payload": e.payload,
        "occurred_at": e.occurred_at.isoformat(),
    }


async def _call_anthropic_replay(rr: dict) -> object:
    """Call Anthropic with a stored raw_request dict. Monkeypatchable in tests."""
    from anthropic import Anthropic

    from src.core.config import get_settings

    s = get_settings()
    if not s.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY not configured")

    client = Anthropic(api_key=s.anthropic_api_key.get_secret_value())
    tools = rr.get("tools") or []
    kwargs: dict = {
        "model": rr.get("model", "claude-haiku-4-5"),
        "max_tokens": rr.get("max_tokens", 1024),
        "system": rr.get("system", ""),
        "messages": rr.get("messages", []),
    }
    if tools:
        kwargs["tools"] = tools

    return await asyncio.to_thread(client.messages.create, **kwargs)


# ── GET /v1/traces/kpis (must come before /{trace_id}) ────────────────────────


@router.get("/v1/traces/kpis")
@limiter.limit("60/minute")
async def traces_kpis(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    now = datetime.now(UTC)
    today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    tomorrow_start = today_start + timedelta(days=1)
    h24_ago = now - timedelta(hours=24)

    cost_today_raw = await session.scalar(
        select(func.sum(Trace.total_cost_usd)).where(
            Trace.started_at >= today_start,
            Trace.started_at < tomorrow_start,
        )
    )

    sparkline: list[dict] = []
    for i in range(6, -1, -1):
        day_start = today_start - timedelta(days=i)
        day_end = day_start + timedelta(days=1)
        day_cost = await session.scalar(
            select(func.sum(Trace.total_cost_usd)).where(
                Trace.started_at >= day_start,
                Trace.started_at < day_end,
            )
        )
        sparkline.append(
            {"date": day_start.date().isoformat(), "cost_usd": _fmt_cost(day_cost or 0)}
        )

    cache_row = (
        await session.execute(
            select(
                func.sum(Trace.total_cache_read_tokens),
                func.sum(Trace.total_input_tokens),
                func.sum(Trace.total_cache_creation_tokens),
            ).where(Trace.started_at >= h24_ago)
        )
    ).one()
    cache_read = cache_row[0] or 0
    input_toks = cache_row[1] or 0
    cache_create = cache_row[2] or 0
    total_tokens = input_toks + cache_read + cache_create
    cache_hit_rate = round(cache_read / total_tokens, 4) if total_tokens > 0 else None

    failure_count_24h = await session.scalar(
        select(func.count())
        .select_from(Trace)
        .where(Trace.status == "failed", Trace.started_at >= h24_ago)
    ) or 0

    oldest_dl_started_at = await session.scalar(
        select(LLMCall.started_at)
        .where(LLMCall.status == "failed", LLMCall.raw_request.is_not(None))
        .order_by(LLMCall.started_at.asc())
        .limit(1)
    )
    oldest_dl_age: float | None = None
    if oldest_dl_started_at is not None:
        oldest_dl_age = now.timestamp() - _to_utc_ts(oldest_dl_started_at)

    return {
        "cost_today_usd": _fmt_cost(cost_today_raw or 0),
        "sparkline_7d": sparkline,
        "cache_hit_rate_24h": cache_hit_rate,
        "failure_count_24h": failure_count_24h,
        "oldest_dead_letter_age_seconds": oldest_dl_age,
    }


# ── GET /v1/traces ─────────────────────────────────────────────────────────────


@router.get("/v1/traces")
@limiter.limit("60/minute")
async def list_traces(
    request: Request,
    trigger_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    trigger_name: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    min_cost: float | None = Query(default=None),
    max_cost: float | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
) -> dict:
    q = select(Trace)
    count_q = select(func.count()).select_from(Trace)

    def _apply(pred: object) -> None:
        nonlocal q, count_q
        q = q.where(pred)  # type: ignore[arg-type]
        count_q = count_q.where(pred)  # type: ignore[arg-type]

    if trigger_type is not None:
        _apply(Trace.trigger_type == trigger_type)
    if status is not None:
        _apply(Trace.status == status)
    if trigger_name is not None:
        _apply(Trace.trigger_name == trigger_name)
    if date_from is not None:
        _apply(Trace.started_at >= date_from)
    if date_to is not None:
        _apply(Trace.started_at <= date_to)
    if min_cost is not None:
        _apply(Trace.total_cost_usd >= min_cost)
    if max_cost is not None:
        _apply(Trace.total_cost_usd <= max_cost)

    total = (await session.execute(count_q)).scalar() or 0
    offset = (page - 1) * page_size
    rows = (
        await session.execute(q.order_by(desc(Trace.started_at)).offset(offset).limit(page_size))
    ).scalars().all()

    return {
        "items": [_trace_to_list_item(t) for t in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ── GET /v1/traces/{trace_id} ──────────────────────────────────────────────────


@router.get("/v1/traces/{trace_id}")
@limiter.limit("60/minute")
async def get_trace(
    request: Request,
    trace_id: _uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> dict:
    result = await session.execute(
        select(Trace)
        .where(Trace.id == trace_id)
        .options(
            selectinload(Trace.cron_steps),
            selectinload(Trace.llm_call_spans),
            selectinload(Trace.tool_call_spans),
            selectinload(Trace.event_spans),
        )
    )
    trace = result.scalar_one_or_none()
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return _trace_to_detail(trace)


# ── POST /v1/traces/{trace_id}/rerun ──────────────────────────────────────────


@router.post("/v1/traces/{trace_id}/rerun")
@limiter.limit("60/minute")
async def rerun_trace(
    request: Request,
    trace_id: _uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> dict:
    trace = await session.get(Trace, trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")

    from src.observability.rerun import dispatch_rerun

    try:
        new_trace_id = await dispatch_rerun(trace)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {"new_trace_id": new_trace_id}


# ── POST /v1/spans/{span_table}/{span_id}/replay ───────────────────────────────


@router.post("/v1/spans/{span_table}/{span_id}/replay")
@limiter.limit("60/minute")
async def replay_span(
    request: Request,
    span_table: str,
    span_id: _uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> dict:
    if span_table not in ("llm_calls", "tool_calls"):
        raise HTTPException(
            status_code=400,
            detail=f"span_table must be 'llm_calls' or 'tool_calls', got {span_table!r}",
        )
    if span_table == "tool_calls":
        raise HTTPException(status_code=501, detail="tool_call replay not implemented in V1")

    row = await session.get(LLMCall, span_id)
    if row is None:
        raise HTTPException(status_code=404, detail="LLM call span not found")
    if row.raw_request is None:
        raise HTTPException(
            status_code=422, detail="raw_request has been swept; cannot replay this span"
        )

    started_at = datetime.now(UTC)
    status = "success"
    usage = None
    raw_response = None
    response_summary = None
    stop_reason = None
    error_message = None
    error_class = None

    try:
        response = await _call_anthropic_replay(row.raw_request)
        finished_at = datetime.now(UTC)
        usage = response.usage
        raw_response = response.model_dump()
        stop_reason = response.stop_reason
        response_summary = {
            "output_text_truncated": next(
                (b.text for b in response.content if b.type == "text"), ""
            )[:200],
            "tool_use_count": sum(1 for b in response.content if b.type == "tool_use"),
            "stop_reason": stop_reason,
        }
    except Exception as exc:
        finished_at = datetime.now(UTC)
        status = "failed"
        error_message = str(exc)
        error_class = type(exc).__name__

    cost = float(compute_cost_usd(row.model, usage)) if usage is not None else 0.0

    new_span = LLMCall(
        id=uuid4(),
        trace_id=row.trace_id,
        span_id=_short_id(),
        parent_span_id=row.parent_span_id,
        call_site=f"{row.call_site}:replay",
        model=row.model,
        provider=row.provider,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=int((finished_at - started_at).total_seconds() * 1000),
        input_tokens=getattr(usage, "input_tokens", None) if usage else None,
        output_tokens=getattr(usage, "output_tokens", None) if usage else None,
        cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", None) if usage else None,
        cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", None) if usage else None,
        stop_reason=stop_reason,
        cost_usd=cost,
        pricing_version=PRICING_VERSION,
        raw_request=row.raw_request,
        raw_response=raw_response,
        request_summary=row.request_summary,
        response_summary=response_summary,
        error_message=error_message,
        error_class=error_class,
    )
    session.add(new_span)
    await session.commit()

    return {"new_span_id": str(new_span.id), "status": new_span.status}
