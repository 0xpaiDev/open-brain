"""Unit tests for src/observability/ and src/llm/pricing.py."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

# ── Helpers ───────────────────────────────────────────────────────────────────


def _usage(
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read: int = 0,
    cache_write: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )


# ── Fixture: DB initialized for observability's internal get_db_context ───────


@pytest_asyncio.fixture
async def obs_db(async_engine, monkeypatch):
    """Patch AsyncSessionLocal so start_trace()'s internal get_db_context uses the test engine."""
    from src.core import database

    factory = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", factory)
    yield


# ── Pricing tests ─────────────────────────────────────────────────────────────


class TestPricing:
    def test_opus_cost(self):
        from src.llm.pricing import compute_cost_usd

        usage = _usage(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = compute_cost_usd("claude-opus-4-7", usage)
        assert cost == Decimal("90.000000")  # 15 + 75

    def test_haiku_cache_read(self):
        from src.llm.pricing import compute_cost_usd

        usage = _usage(cache_read=1_000_000)
        cost = compute_cost_usd("claude-haiku-4-5", usage)
        assert cost == Decimal("0.100000")

    def test_unknown_model_returns_zero(self):
        from src.llm.pricing import compute_cost_usd

        cost = compute_cost_usd("claude-unknown-future", _usage(input_tokens=1000))
        assert cost == Decimal("0")

    def test_zero_tokens_is_zero(self):
        from src.llm.pricing import compute_cost_usd

        cost = compute_cost_usd("claude-sonnet-4-6", _usage())
        assert cost == Decimal("0")

    def test_partial_tokens(self):
        from src.llm.pricing import compute_cost_usd

        # 500 input + 200 output on sonnet
        usage = _usage(input_tokens=500, output_tokens=200)
        cost = compute_cost_usd("claude-sonnet-4-6", usage)
        expected = Decimal("500") * Decimal("3") / Decimal("1000000") + Decimal(
            "200"
        ) * Decimal("15") / Decimal("1000000")
        assert cost == expected.quantize(Decimal("0.000001"))


# ── Trace lifecycle ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_trace_creates_row(obs_db, async_session):
    from src.core.models import Trace
    from src.observability.context import current_trace_id, start_trace

    async with start_trace(trigger_type="cron", trigger_name="test_job"):
        tid = current_trace_id()
        assert tid is not None

    # Flush the test session to see changes from the observability session
    async_session.expire_all()
    rows = (await async_session.execute(select(Trace))).scalars().all()
    assert len(rows) == 1
    trace = rows[0]
    assert trace.status == "success"
    assert trace.trigger_type == "cron"
    assert trace.trigger_name == "test_job"
    assert trace.finished_at is not None
    assert trace.duration_ms is not None


@pytest.mark.asyncio
async def test_start_trace_records_failure(obs_db, async_session):
    from src.core.models import Trace
    from src.observability.context import start_trace

    with pytest.raises(ValueError, match="boom"):
        async with start_trace(trigger_type="cron", trigger_name="fail_job"):
            raise ValueError("boom")

    async_session.expire_all()
    rows = (await async_session.execute(select(Trace))).scalars().all()
    assert len(rows) == 1
    trace = rows[0]
    assert trace.status == "failed"
    assert "boom" in trace.error_message
    assert trace.error_class == "ValueError"


@pytest.mark.asyncio
async def test_current_trace_id_none_outside_context():
    from src.observability.context import current_trace_id

    assert current_trace_id() is None


# ── start_step ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_step_creates_cron_step(obs_db, async_session):
    from src.core.models import CronStep
    from src.observability.context import start_step, start_trace

    async with start_trace(trigger_type="cron", trigger_name="job"):
        async with start_step("load_inputs"):
            pass
        async with start_step("run_llm"):
            pass

    async_session.expire_all()
    steps = (await async_session.execute(select(CronStep))).scalars().all()
    assert len(steps) == 2
    names = {s.step_name for s in steps}
    assert names == {"load_inputs", "run_llm"}
    assert all(s.status == "success" for s in steps)


@pytest.mark.asyncio
async def test_start_step_noop_outside_trace():
    from src.observability.context import start_step

    # Should not raise
    async with start_step("orphan_step"):
        pass


@pytest.mark.asyncio
async def test_start_step_records_failure(obs_db, async_session):
    from src.core.models import CronStep
    from src.observability.context import start_step, start_trace

    with pytest.raises(RuntimeError):
        async with start_trace(trigger_type="cron", trigger_name="job"):
            async with start_step("bad_step"):
                raise RuntimeError("step failed")

    async_session.expire_all()
    steps = (await async_session.execute(select(CronStep))).scalars().all()
    assert len(steps) == 1
    assert steps[0].status == "failed"
    assert "step failed" in steps[0].error_message


# ── record_llm_call ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_llm_call_creates_row(obs_db, async_session):
    from src.core.models import LLMCall
    from src.observability.context import start_trace
    from src.observability.recording import record_llm_call

    usage = _usage(input_tokens=1000, output_tokens=500)

    async with start_trace(trigger_type="cron", trigger_name="job"):
        await record_llm_call(
            call_site="synthesis.run",
            model="claude-haiku-4-5",
            status="success",
            usage=usage,
            request_summary={"message_count": 3},
        )

    async_session.expire_all()
    calls = (await async_session.execute(select(LLMCall))).scalars().all()
    assert len(calls) == 1
    c = calls[0]
    assert c.call_site == "synthesis.run"
    assert c.model == "claude-haiku-4-5"
    assert c.status == "success"
    assert c.input_tokens == 1000
    assert c.output_tokens == 500
    assert float(c.cost_usd) > 0


@pytest.mark.asyncio
async def test_record_llm_call_noop_outside_trace():
    from src.observability.recording import record_llm_call

    # Should not raise even without an active trace
    await record_llm_call(
        call_site="test",
        model="claude-haiku-4-5",
        status="success",
        request_summary={},
    )


# ── record_tool_call ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_tool_call_creates_row(obs_db, async_session):
    from src.core.models import ToolCall
    from src.observability.context import start_trace
    from src.observability.recording import record_tool_call

    async with start_trace(trigger_type="chat", trigger_name="tool_loop"):
        await record_tool_call(
            tool_name="search_memory",
            args={"query": "test"},
            status="success",
            result={"hits": 3},
        )

    async_session.expire_all()
    calls = (await async_session.execute(select(ToolCall))).scalars().all()
    assert len(calls) == 1
    tc = calls[0]
    assert tc.tool_name == "search_memory"
    assert tc.status == "success"
    assert tc.args == {"query": "test"}


@pytest.mark.asyncio
async def test_record_tool_call_noop_outside_trace():
    from src.observability.recording import record_tool_call

    await record_tool_call(tool_name="test", args={}, status="success")


# ── contextvar isolation ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_contextvar_isolation_across_tasks(obs_db):
    """Two concurrent tasks should not share trace context."""
    from src.observability.context import current_trace_id, start_trace

    results: list[str | None] = []

    async def task_a():
        async with start_trace(trigger_type="cron", trigger_name="a"):
            await asyncio.sleep(0)
            results.append(current_trace_id())

    async def task_b():
        await asyncio.sleep(0)
        results.append(current_trace_id())

    await asyncio.gather(task_a(), task_b())

    # task_a should have a trace_id, task_b should not (runs outside a trace)
    assert any(r is not None for r in results)
    assert any(r is None for r in results)


# ── Retention sweeper ─────────────────────────────────────────────────────────


def _make_trace(status: str, age_days: int):
    """Build a Trace ORM object with started_at set to age_days ago."""
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from src.core.models import Trace

    return Trace(
        id=uuid4(),
        trigger_type="cron",
        trigger_name="test_job",
        status=status,
        started_at=datetime.now(UTC) - timedelta(days=age_days),
    )


def _make_llm_call(trace_id):
    """Build an LLMCall ORM object with raw payloads populated."""
    from uuid import uuid4

    from src.core.models import LLMCall

    return LLMCall(
        id=uuid4(),
        trace_id=trace_id,
        span_id="span-1",
        call_site="test.call",
        model="claude-haiku-4-5",
        status="success",
        pricing_version="v1",
        request_summary={"message_count": 1},
        raw_request={"messages": [{"role": "user", "content": "hello"}]},
        raw_response={"content": [{"text": "hi"}]},
    )


class TestObservabilitySweep:
    @pytest.mark.asyncio
    async def test_sweep_nulls_raw_payloads_on_old_successful_traces(self, async_session):
        from src.jobs.observability_sweep import sweep_raw_payloads

        trace = _make_trace(status="success", age_days=91)
        async_session.add(trace)
        await async_session.flush()

        call = _make_llm_call(trace_id=trace.id)
        async_session.add(call)
        await async_session.flush()

        rows_swept = await sweep_raw_payloads(async_session, ttl_days=90)

        assert rows_swept == 1
        await async_session.refresh(call)
        assert call.raw_request is None
        assert call.raw_response is None

    @pytest.mark.asyncio
    async def test_sweep_exempts_failed_traces(self, async_session):
        from src.jobs.observability_sweep import sweep_raw_payloads

        trace = _make_trace(status="failed", age_days=91)
        async_session.add(trace)
        await async_session.flush()

        call = _make_llm_call(trace_id=trace.id)
        async_session.add(call)
        await async_session.flush()

        rows_swept = await sweep_raw_payloads(async_session, ttl_days=90)

        assert rows_swept == 0
        await async_session.refresh(call)
        assert call.raw_request is not None
        assert call.raw_response is not None

    @pytest.mark.asyncio
    async def test_sweep_exempts_running_traces(self, async_session):
        from src.jobs.observability_sweep import sweep_raw_payloads

        trace = _make_trace(status="running", age_days=91)
        async_session.add(trace)
        await async_session.flush()

        call = _make_llm_call(trace_id=trace.id)
        async_session.add(call)
        await async_session.flush()

        rows_swept = await sweep_raw_payloads(async_session, ttl_days=90)

        assert rows_swept == 0
        await async_session.refresh(call)
        assert call.raw_request is not None
        assert call.raw_response is not None

    @pytest.mark.asyncio
    async def test_sweep_keeps_recent_rows(self, async_session):
        from src.jobs.observability_sweep import sweep_raw_payloads

        trace = _make_trace(status="success", age_days=1)
        async_session.add(trace)
        await async_session.flush()

        call = _make_llm_call(trace_id=trace.id)
        async_session.add(call)
        await async_session.flush()

        rows_swept = await sweep_raw_payloads(async_session, ttl_days=90)

        assert rows_swept == 0
        await async_session.refresh(call)
        assert call.raw_request is not None
        assert call.raw_response is not None
