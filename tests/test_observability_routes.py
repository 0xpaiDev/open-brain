"""Tests for observability API routes.

Covers all 5 routes:
  GET  /v1/traces/kpis
  GET  /v1/traces
  GET  /v1/traces/{trace_id}
  POST /v1/traces/{trace_id}/rerun
  POST /v1/spans/{span_table}/{span_id}/replay
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.core.models import CronStep, LLMCall, ObsEvent, ToolCall, Trace

# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client(async_session, monkeypatch):
    monkeypatch.setenv("SQLALCHEMY_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("API_KEY", "test-secret-key")

    from src.api.main import app
    from src.core.database import get_db

    async def override_get_db():
        yield async_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth() -> dict:
    return {"X-API-Key": "test-secret-key"}


# ── Fixture helpers ────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


async def _make_trace(
    session,
    *,
    trigger_type: str = "cron",
    trigger_name: str | None = "synthesis",
    status: str = "success",
    started_at: datetime | None = None,
    total_cost_usd: float | None = None,
    total_input_tokens: int | None = None,
    total_cache_read_tokens: int | None = None,
    total_cache_creation_tokens: int | None = None,
    error_message: str | None = None,
) -> Trace:
    sa = started_at or _now()
    t = Trace(
        id=uuid4(),
        trigger_type=trigger_type,
        trigger_name=trigger_name,
        status=status,
        started_at=sa,
        finished_at=sa + timedelta(seconds=2),
        duration_ms=2000,
        total_cost_usd=total_cost_usd,
        total_input_tokens=total_input_tokens,
        total_cache_read_tokens=total_cache_read_tokens,
        total_cache_creation_tokens=total_cache_creation_tokens,
        error_message=error_message,
    )
    session.add(t)
    await session.flush()
    await session.commit()
    return t


async def _make_llm_call(
    session,
    *,
    trace_id,
    status: str = "success",
    raw_request: dict | None = None,
    raw_response: dict | None = None,
    started_at: datetime | None = None,
    cost_usd: float = 0.001,
) -> LLMCall:
    sa = started_at or _now()
    lc = LLMCall(
        id=uuid4(),
        trace_id=trace_id,
        span_id="abc123",
        parent_span_id=None,
        call_site="llm.complete",
        model="claude-haiku-4-5",
        provider="anthropic",
        status=status,
        started_at=sa,
        finished_at=sa + timedelta(milliseconds=300),
        duration_ms=300,
        cost_usd=cost_usd,
        pricing_version="2026-05",
        raw_request=raw_request,
        raw_response=raw_response,
        request_summary={"message_count": 1},
    )
    session.add(lc)
    await session.flush()
    await session.commit()
    return lc


# ── GET /v1/traces/kpis ────────────────────────────────────────────────────────


class TestTracesKpis:
    async def test_empty_db(self, client, auth):
        resp = await client.get("/v1/traces/kpis", headers=auth)
        assert resp.status_code == 200
        body = resp.json()
        assert body["cost_in_range_usd"] == "0.000000"
        assert len(body["sparkline_7d"]) == 7
        assert body["cache_hit_rate_24h"] is None
        assert body["failure_count_24h"] == 0
        assert body["oldest_dead_letter_age_seconds"] is None

    async def test_cost_today(self, client, auth, async_session):
        now = _now()
        await _make_trace(async_session, total_cost_usd=0.05, started_at=now)
        await _make_trace(async_session, total_cost_usd=0.03, started_at=now)
        # Old trace — should not count
        await _make_trace(
            async_session, total_cost_usd=1.0, started_at=now - timedelta(days=2)
        )

        resp = await client.get("/v1/traces/kpis", headers=auth)
        assert resp.status_code == 200
        body = resp.json()
        assert float(body["cost_in_range_usd"]) == pytest.approx(0.08, abs=1e-5)

    async def test_cost_date_range(self, client, auth, async_session):
        now = _now()
        five_days_ago = now - timedelta(days=5)
        # Trace on 5-days-ago date
        await _make_trace(async_session, total_cost_usd=0.07, started_at=five_days_ago)
        # Trace today — should NOT be included when filtering to 5-days-ago
        await _make_trace(async_session, total_cost_usd=0.99, started_at=now)

        date_str = five_days_ago.date().isoformat()
        resp = await client.get(
            f"/v1/traces/kpis?date_from={date_str}&date_to={date_str}", headers=auth
        )
        assert resp.status_code == 200
        body = resp.json()
        assert float(body["cost_in_range_usd"]) == pytest.approx(0.07, abs=1e-5)

    async def test_sparkline_has_7_entries(self, client, auth, async_session):
        now = _now()
        await _make_trace(async_session, total_cost_usd=0.1, started_at=now)
        resp = await client.get("/v1/traces/kpis", headers=auth)
        sparkline = resp.json()["sparkline_7d"]
        assert len(sparkline) == 7
        for entry in sparkline:
            assert "date" in entry
            assert "cost_usd" in entry

    async def test_cache_hit_rate(self, client, auth, async_session):
        now = _now()
        await _make_trace(
            async_session,
            started_at=now,
            total_input_tokens=800,
            total_cache_read_tokens=200,
            total_cache_creation_tokens=0,
        )
        resp = await client.get("/v1/traces/kpis", headers=auth)
        # 200 / (800 + 200 + 0) = 0.2
        assert resp.json()["cache_hit_rate_24h"] == pytest.approx(0.2, abs=1e-4)

    async def test_failure_count_24h(self, client, auth, async_session):
        now = _now()
        await _make_trace(async_session, status="failed", started_at=now)
        await _make_trace(async_session, status="failed", started_at=now)
        await _make_trace(async_session, status="success", started_at=now)
        # Old failure — outside 24h window
        await _make_trace(
            async_session, status="failed", started_at=now - timedelta(hours=25)
        )
        resp = await client.get("/v1/traces/kpis", headers=auth)
        assert resp.json()["failure_count_24h"] == 2

    async def test_oldest_dead_letter(self, client, auth, async_session):
        trace = await _make_trace(async_session)
        # Failed LLM call with raw_request present
        await _make_llm_call(
            async_session,
            trace_id=trace.id,
            status="failed",
            raw_request={"model": "claude-haiku-4-5", "messages": []},
        )
        resp = await client.get("/v1/traces/kpis", headers=auth)
        age = resp.json()["oldest_dead_letter_age_seconds"]
        assert age is not None
        assert age >= 0

    async def test_no_dead_letter_when_swept(self, client, auth, async_session):
        from sqlalchemy import null, update

        trace = await _make_trace(async_session)
        lc = await _make_llm_call(
            async_session,
            trace_id=trace.id,
            status="failed",
            raw_request={"model": "claude-haiku-4-5", "messages": []},
        )
        # Simulate sweeper: force SQL NULL (not JSON null) on raw_request
        await async_session.execute(
            update(LLMCall).where(LLMCall.id == lc.id).values(raw_request=null())
        )
        await async_session.commit()
        resp = await client.get("/v1/traces/kpis", headers=auth)
        assert resp.json()["oldest_dead_letter_age_seconds"] is None

    async def test_requires_auth(self, client):
        resp = await client.get("/v1/traces/kpis")
        assert resp.status_code == 401


# ── GET /v1/traces ─────────────────────────────────────────────────────────────


class TestListTraces:
    async def test_empty_returns_empty(self, client, auth):
        resp = await client.get("/v1/traces", headers=auth)
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0

    async def test_returns_all(self, client, auth, async_session):
        await _make_trace(async_session)
        await _make_trace(async_session, trigger_type="http")
        resp = await client.get("/v1/traces", headers=auth)
        body = resp.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2

    async def test_filter_trigger_type(self, client, auth, async_session):
        await _make_trace(async_session, trigger_type="cron")
        await _make_trace(async_session, trigger_type="http")
        resp = await client.get("/v1/traces?trigger_type=cron", headers=auth)
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["trigger_type"] == "cron"

    async def test_filter_status(self, client, auth, async_session):
        await _make_trace(async_session, status="success")
        await _make_trace(async_session, status="failed")
        resp = await client.get("/v1/traces?status=failed", headers=auth)
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["status"] == "failed"

    async def test_filter_trigger_name(self, client, auth, async_session):
        await _make_trace(async_session, trigger_name="synthesis")
        await _make_trace(async_session, trigger_name="pulse")
        resp = await client.get("/v1/traces?trigger_name=synthesis", headers=auth)
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["trigger_name"] == "synthesis"

    async def test_filter_date_from(self, client, auth, async_session):
        now = _now()
        await _make_trace(async_session, started_at=now)
        await _make_trace(async_session, started_at=now - timedelta(days=3))
        # Use YYYY-MM-DD date string (date_from accepts _date, not datetime)
        cutoff = (now - timedelta(days=1)).date().isoformat()
        resp = await client.get("/v1/traces", headers=auth, params={"date_from": cutoff})
        assert resp.json()["total"] == 1

    async def test_filter_date_to(self, client, auth, async_session):
        now = _now()
        await _make_trace(async_session, started_at=now)
        await _make_trace(async_session, started_at=now - timedelta(days=3))
        # Use YYYY-MM-DD date string; date_to is inclusive-day (< date_to + 1 day)
        cutoff = (now - timedelta(days=1)).date().isoformat()
        resp = await client.get("/v1/traces", headers=auth, params={"date_to": cutoff})
        assert resp.json()["total"] == 1

    async def test_filter_min_cost(self, client, auth, async_session):
        await _make_trace(async_session, total_cost_usd=0.001)
        await _make_trace(async_session, total_cost_usd=0.5)
        resp = await client.get("/v1/traces?min_cost=0.1", headers=auth)
        assert resp.json()["total"] == 1

    async def test_filter_max_cost(self, client, auth, async_session):
        await _make_trace(async_session, total_cost_usd=0.001)
        await _make_trace(async_session, total_cost_usd=0.5)
        resp = await client.get("/v1/traces?max_cost=0.1", headers=auth)
        assert resp.json()["total"] == 1

    async def test_ordered_desc_by_started_at(self, client, auth, async_session):
        now = _now()
        early = await _make_trace(async_session, started_at=now - timedelta(hours=2))
        late = await _make_trace(async_session, started_at=now)
        resp = await client.get("/v1/traces", headers=auth)
        items = resp.json()["items"]
        assert items[0]["id"] == str(late.id)
        assert items[1]["id"] == str(early.id)

    async def test_pagination(self, client, auth, async_session):
        now = _now()
        for i in range(5):
            await _make_trace(async_session, started_at=now - timedelta(hours=i))
        resp = await client.get("/v1/traces?page=2&page_size=2", headers=auth)
        body = resp.json()
        assert len(body["items"]) == 2
        assert body["total"] == 5
        assert body["page"] == 2
        assert body["page_size"] == 2

    async def test_list_item_shape(self, client, auth, async_session):
        await _make_trace(async_session, total_cost_usd=0.01)
        resp = await client.get("/v1/traces", headers=auth)
        item = resp.json()["items"][0]
        for key in (
            "id", "trigger_type", "trigger_name", "status",
            "started_at", "finished_at", "duration_ms",
            "total_cost_usd", "llm_call_count", "tool_call_count",
            "error_message", "error_class",
        ):
            assert key in item, f"missing key: {key}"
        # Cost serialized as string
        assert isinstance(item["total_cost_usd"], str)

    async def test_requires_auth(self, client):
        resp = await client.get("/v1/traces")
        assert resp.status_code == 401


# ── GET /v1/traces/{trace_id} ──────────────────────────────────────────────────


class TestGetTrace:
    async def test_404_for_missing(self, client, auth):
        resp = await client.get(f"/v1/traces/{uuid4()}", headers=auth)
        assert resp.status_code == 404

    async def test_returns_trace(self, client, auth, async_session):
        trace = await _make_trace(async_session, total_cost_usd=0.02)
        resp = await client.get(f"/v1/traces/{trace.id}", headers=auth)
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == str(trace.id)
        assert body["trigger_type"] == trace.trigger_type
        assert isinstance(body["total_cost_usd"], str)

    async def test_includes_child_spans(self, client, auth, async_session):
        trace = await _make_trace(async_session)

        # Add a CronStep
        cs = CronStep(
            id=uuid4(),
            trace_id=trace.id,
            span_id="span1",
            step_name="do_thing",
            status="success",
            started_at=_now(),
        )
        async_session.add(cs)

        # Add an LLMCall
        lc = LLMCall(
            id=uuid4(),
            trace_id=trace.id,
            span_id="span2",
            call_site="llm.complete",
            model="claude-haiku-4-5",
            provider="anthropic",
            status="success",
            cost_usd=0.001,
            pricing_version="2026-05",
            raw_request={"secret": "should_not_appear"},
            raw_response={"secret": "should_not_appear"},
            request_summary={"message_count": 1},
        )
        async_session.add(lc)

        # Add a ToolCall
        tc = ToolCall(
            id=uuid4(),
            trace_id=trace.id,
            span_id="span3",
            parent_span_id="span2",
            tool_name="search_memory",
            status="success",
            args={"query": "test"},
        )
        async_session.add(tc)

        # Add an ObsEvent
        ev = ObsEvent(
            id=uuid4(),
            trace_id=trace.id,
            span_id="span4",
            event_type="db.write",
            level="info",
        )
        async_session.add(ev)

        await async_session.commit()

        resp = await client.get(f"/v1/traces/{trace.id}", headers=auth)
        assert resp.status_code == 200
        body = resp.json()

        assert len(body["cron_steps"]) == 1
        assert body["cron_steps"][0]["step_name"] == "do_thing"

        assert len(body["llm_calls"]) == 1
        llm = body["llm_calls"][0]
        # raw blobs must NOT be present
        assert "raw_request" not in llm
        assert "raw_response" not in llm
        assert "request_summary" in llm

        assert len(body["tool_calls"]) == 1
        assert body["tool_calls"][0]["tool_name"] == "search_memory"

        assert len(body["events"]) == 1
        assert body["events"][0]["event_type"] == "db.write"

    async def test_requires_auth(self, client, async_session):
        trace = await _make_trace(async_session)
        resp = await client.get(f"/v1/traces/{trace.id}")
        assert resp.status_code == 401


# ── POST /v1/traces/{trace_id}/rerun ──────────────────────────────────────────


class TestRerunTrace:
    async def test_404_for_missing(self, client, auth):
        resp = await client.post(f"/v1/traces/{uuid4()}/rerun", headers=auth)
        assert resp.status_code == 404

    async def test_422_no_handler(self, client, auth, async_session):
        trace = await _make_trace(async_session, trigger_type="unregistered_type_xyz")
        resp = await client.post(f"/v1/traces/{trace.id}/rerun", headers=auth)
        assert resp.status_code == 422
        assert "unregistered_type_xyz" in resp.json()["detail"]

    async def test_rerun_calls_handler(self, client, auth, async_session, monkeypatch):
        from src.observability import rerun as rerun_mod

        new_id = str(uuid4())
        called_with: list = []

        async def fake_dispatch(trace):
            called_with.append(trace.id)
            return new_id

        monkeypatch.setattr(rerun_mod, "dispatch_rerun", fake_dispatch)

        trace = await _make_trace(async_session)
        resp = await client.post(f"/v1/traces/{trace.id}/rerun", headers=auth)
        assert resp.status_code == 200
        body = resp.json()
        assert body["new_trace_id"] == new_id
        assert len(called_with) == 1

    async def test_requires_auth(self, client, async_session):
        trace = await _make_trace(async_session)
        resp = await client.post(f"/v1/traces/{trace.id}/rerun")
        assert resp.status_code == 401


# ── POST /v1/spans/{span_table}/{span_id}/replay ───────────────────────────────


class TestReplaySpan:
    async def test_400_invalid_span_table(self, client, auth):
        resp = await client.post(f"/v1/spans/bad_table/{uuid4()}/replay", headers=auth)
        assert resp.status_code == 400
        assert "bad_table" in resp.json()["detail"]

    async def test_501_tool_calls(self, client, auth):
        resp = await client.post(f"/v1/spans/tool_calls/{uuid4()}/replay", headers=auth)
        assert resp.status_code == 501

    async def test_404_missing_llm_call(self, client, auth):
        resp = await client.post(f"/v1/spans/llm_calls/{uuid4()}/replay", headers=auth)
        assert resp.status_code == 404

    async def test_422_swept_raw_request(self, client, auth, async_session):
        trace = await _make_trace(async_session)
        lc = await _make_llm_call(async_session, trace_id=trace.id, raw_request=None)
        resp = await client.post(f"/v1/spans/llm_calls/{lc.id}/replay", headers=auth)
        assert resp.status_code == 422
        assert "swept" in resp.json()["detail"]

    async def test_replay_success(self, client, auth, async_session, monkeypatch):
        import src.api.routes.observability as obs_routes

        mock_usage = SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        mock_response = SimpleNamespace(
            usage=mock_usage,
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="hello")],
            model_dump=lambda: {"id": "msg_mock"},
        )

        async def fake_replay(rr: dict) -> object:
            return mock_response

        monkeypatch.setattr(obs_routes, "_call_anthropic_replay", fake_replay)

        trace = await _make_trace(async_session)
        rr = {"model": "claude-haiku-4-5", "messages": [{"role": "user", "content": "hi"}]}
        lc = await _make_llm_call(async_session, trace_id=trace.id, raw_request=rr)

        resp = await client.post(f"/v1/spans/llm_calls/{lc.id}/replay", headers=auth)
        assert resp.status_code == 200
        body = resp.json()
        assert "new_span_id" in body
        assert body["status"] == "success"

        # Verify new sibling row was written
        from sqlalchemy import select as sa_select
        rows = (
            await async_session.execute(
                sa_select(LLMCall).where(LLMCall.trace_id == lc.trace_id)
            )
        ).scalars().all()
        # Original + new replay sibling
        assert len(rows) == 2
        replay_row = next(r for r in rows if str(r.id) == body["new_span_id"])
        assert replay_row.call_site.endswith(":replay")
        assert replay_row.status == "success"

    async def test_replay_handles_llm_error(self, client, auth, async_session, monkeypatch):
        import src.api.routes.observability as obs_routes

        async def fake_replay_fail(rr: dict) -> object:
            raise RuntimeError("Anthropic 500")

        monkeypatch.setattr(obs_routes, "_call_anthropic_replay", fake_replay_fail)

        trace = await _make_trace(async_session)
        rr = {"model": "claude-haiku-4-5", "messages": []}
        lc = await _make_llm_call(async_session, trace_id=trace.id, raw_request=rr)

        resp = await client.post(f"/v1/spans/llm_calls/{lc.id}/replay", headers=auth)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "failed"

    async def test_requires_auth(self, client):
        resp = await client.post(f"/v1/spans/llm_calls/{uuid4()}/replay")
        assert resp.status_code == 401


# ── GET /v1/llm-calls/{llm_call_id} ───────────────────────────────────────────


class TestGetLLMCallRaw:
    async def test_get_llm_call_raw_returns_payloads(self, client, auth, async_session):
        trace = await _make_trace(async_session)
        lc = await _make_llm_call(
            async_session,
            trace_id=trace.id,
            raw_request={"model": "haiku"},
            raw_response={"content": "hello"},
        )

        resp = await client.get(f"/v1/llm-calls/{lc.id}", headers=auth)
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == str(lc.id)
        assert body["raw_request"] == {"model": "haiku"}
        assert body["raw_response"] == {"content": "hello"}
        assert body["request_summary"] == {"message_count": 1}

    async def test_get_llm_call_raw_404(self, client, auth):
        resp = await client.get(
            "/v1/llm-calls/00000000-0000-0000-0000-000000000001", headers=auth
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "LLM call not found"

    async def test_get_llm_call_raw_requires_auth(self, client, async_session):
        trace = await _make_trace(async_session)
        lc = await _make_llm_call(async_session, trace_id=trace.id)
        resp = await client.get(f"/v1/llm-calls/{lc.id}")
        assert resp.status_code == 401
