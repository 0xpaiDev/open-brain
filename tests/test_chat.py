"""Tests for POST /v1/chat endpoint and shared RAG prompt utilities.

Covers:
  - Prompt extraction: build_rag_system_prompt, build_rag_user_message
  - Query formulation: build_query_formulation_content, QUERY_FORMULATION_SYSTEM
  - Chat endpoint: happy path, formulation fallback, model validation,
    empty history, empty search results, external context, history limit

All LLM and embedding calls are mocked — no production services hit.
Tests run on SQLite (in-memory) via conftest.py fixtures.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.llm.rag_prompts import (
    QUERY_FORMULATION_SYSTEM,
    build_query_formulation_content,
    build_rag_system_prompt,
    build_rag_user_message,
)
from src.core.models import MemoryItem, RawMemory
from src.retrieval.search import SearchResult


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client(async_session: AsyncSession, monkeypatch):
    """Test client with DB overridden to use in-memory SQLite session."""
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
def auth_headers() -> dict:
    return {"X-API-Key": "test-secret-key"}


def _mock_search_results() -> list[SearchResult]:
    """Create sample SearchResult objects for tests."""
    return [
        SearchResult(
            id="aaa-111",
            content="Python is a programming language.",
            summary="Python fact",
            type="memory",
            importance_score=0.8,
            combined_score=0.75,
            created_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
            project="learning",
        ),
        SearchResult(
            id="bbb-222",
            content="PostgreSQL is the production database.",
            summary="DB choice",
            type="decision",
            importance_score=0.9,
            combined_score=0.85,
            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            project=None,
        ),
    ]


# ── Group 1: Prompt utilities (unit tests) ───────────────────────────────────


class TestBuildRagSystemPrompt:
    def test_with_context(self):
        prompt = build_rag_system_prompt("Some relevant memory.")
        assert "<context>" in prompt
        assert "Some relevant memory." in prompt
        assert "</context>" in prompt
        assert "personal memory system" in prompt

    def test_empty_context(self):
        prompt = build_rag_system_prompt("")
        assert "<context>" not in prompt
        assert "No relevant memories" in prompt

    def test_whitespace_only_context(self):
        prompt = build_rag_system_prompt("   \n  ")
        assert "<context>" not in prompt
        assert "No relevant memories" in prompt


class TestBuildRagUserMessage:
    def test_wraps_in_user_input_tags(self):
        msg = build_rag_user_message("What is Python?")
        assert msg == "<user_input>What is Python?</user_input>"

    def test_empty_query(self):
        msg = build_rag_user_message("")
        assert msg == "<user_input></user_input>"


class TestQueryFormulationSystem:
    def test_constant_exists_and_has_content(self):
        assert isinstance(QUERY_FORMULATION_SYSTEM, str)
        assert len(QUERY_FORMULATION_SYSTEM) > 50
        assert "search query" in QUERY_FORMULATION_SYSTEM.lower()


class TestBuildQueryFormulationContent:
    def test_with_history_and_context(self):
        history = [
            {"role": "user", "content": "Tell me about Python"},
            {"role": "assistant", "content": "Python is a language."},
            {"role": "user", "content": "What about its typing?"},
            {"role": "assistant", "content": "It supports type hints."},
        ]
        content = build_query_formulation_content(
            history=history,
            external_context="Python was created by Guido van Rossum.",
            user_message="How does async work?",
        )
        assert "Recent conversation:" in content
        assert "Tell me about Python" in content
        assert "Additional context:" in content
        assert "Guido van Rossum" in content
        assert "Current message: How does async work?" in content

    def test_empty_history(self):
        content = build_query_formulation_content(
            history=[],
            external_context=None,
            user_message="What is architecture?",
        )
        assert "Recent conversation:" not in content
        assert "Additional context:" not in content
        assert "Current message: What is architecture?" in content

    def test_history_tail_limit(self):
        """Only last 4 messages are included."""
        history = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
        content = build_query_formulation_content(
            history=history,
            external_context=None,
            user_message="latest",
        )
        assert "msg6" in content
        assert "msg9" in content
        # msg0 should be excluded (older than tail of 4)
        assert "msg0" not in content

    def test_external_context_truncation(self):
        """External context is truncated to 2000 chars."""
        long_context = "x" * 5000
        content = build_query_formulation_content(
            history=[],
            external_context=long_context,
            user_message="test",
        )
        # 2000 chars of context + label text, should not contain full 5000
        context_section = content.split("Additional context:\n")[1].split("\n\n")[0]
        assert len(context_section) == 2000


# ── Group 2: Chat endpoint (integration tests) ──────────────────────────────


def _patch_chat_deps(monkeypatch, search_results=None, formulated_query="optimised query",
                     synthesis_response="Here is the answer."):
    """Patch LLM clients and hybrid_search for chat endpoint tests."""
    if search_results is None:
        search_results = _mock_search_results()

    # Mock AnthropicClient
    mock_anthropic_instance = MagicMock()
    mock_anthropic_instance.complete = AsyncMock(return_value=formulated_query)
    mock_anthropic_instance.complete_with_history = AsyncMock(return_value=synthesis_response)
    mock_anthropic_cls = MagicMock(return_value=mock_anthropic_instance)
    monkeypatch.setattr("src.api.routes.chat.AnthropicClient", mock_anthropic_cls)

    # Mock VoyageEmbeddingClient
    mock_voyage_instance = MagicMock()
    mock_voyage_instance.embed = AsyncMock(return_value=[0.1] * 1024)
    mock_voyage_cls = MagicMock(return_value=mock_voyage_instance)
    monkeypatch.setattr("src.api.routes.chat.VoyageEmbeddingClient", mock_voyage_cls)

    # Mock hybrid_search
    mock_search = AsyncMock(return_value=search_results)
    monkeypatch.setattr("src.api.routes.chat.hybrid_search", mock_search)

    return mock_anthropic_instance, mock_voyage_instance, mock_search


@pytest.mark.asyncio
async def test_chat_happy_path(client: AsyncClient, auth_headers: dict, monkeypatch):
    """Full pipeline: formulate → search → synthesize → respond with sources."""
    mock_anthropic, mock_voyage, mock_search = _patch_chat_deps(monkeypatch)

    resp = await client.post(
        "/v1/chat",
        json={
            "message": "What databases do we use?",
            "history": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
            ],
        },
        headers=auth_headers,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["response"] == "Here is the answer."
    assert data["model"] == "claude-haiku-4-5-20251001"
    assert data["search_query"] == "optimised query"
    assert len(data["sources"]) == 2
    assert data["sources"][0]["id"] == "aaa-111"
    assert data["sources"][1]["id"] == "bbb-222"

    # Verify formulation was called
    mock_anthropic.complete.assert_awaited_once()
    # Verify synthesis was called with model override
    mock_anthropic.complete_with_history.assert_awaited_once()
    # Verify embedding was called with formulated query
    mock_voyage.embed.assert_awaited_once_with("optimised query")


@pytest.mark.asyncio
async def test_chat_empty_history(client: AsyncClient, auth_headers: dict, monkeypatch):
    """Chat with no history — single-turn."""
    _patch_chat_deps(monkeypatch)

    resp = await client.post(
        "/v1/chat",
        json={"message": "What is Python?"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["response"] == "Here is the answer."


@pytest.mark.asyncio
async def test_chat_formulation_fallback(client: AsyncClient, auth_headers: dict, monkeypatch):
    """When query formulation fails, raw message is used as search query."""
    from src.llm.client import ExtractionFailed

    mock_anthropic, _, _ = _patch_chat_deps(monkeypatch)
    mock_anthropic.complete = AsyncMock(side_effect=ExtractionFailed("LLM timeout"))

    resp = await client.post(
        "/v1/chat",
        json={"message": "What is the architecture?"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    data = resp.json()
    # Fallback: raw message used as search query
    assert data["search_query"] == "What is the architecture?"


@pytest.mark.asyncio
async def test_chat_formulation_empty_response_fallback(
    client: AsyncClient, auth_headers: dict, monkeypatch
):
    """When formulation returns empty string, raw message is used."""
    _patch_chat_deps(monkeypatch, formulated_query="   ")

    resp = await client.post(
        "/v1/chat",
        json={"message": "Tell me about X"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert resp.json()["search_query"] == "Tell me about X"


@pytest.mark.asyncio
async def test_chat_invalid_model(client: AsyncClient, auth_headers: dict, monkeypatch):
    """Invalid model name returns 422."""
    _patch_chat_deps(monkeypatch)

    resp = await client.post(
        "/v1/chat",
        json={"message": "test", "model": "gpt-4o"},
        headers=auth_headers,
    )

    assert resp.status_code == 422
    assert "Model must be one of" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_chat_sonnet_model(client: AsyncClient, auth_headers: dict, monkeypatch):
    """Sonnet model is accepted and passed to synthesis."""
    mock_anthropic, _, _ = _patch_chat_deps(monkeypatch)

    resp = await client.post(
        "/v1/chat",
        json={"message": "test", "model": "claude-sonnet-4-6"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert resp.json()["model"] == "claude-sonnet-4-6"
    # Verify synthesis used sonnet
    call_kwargs = mock_anthropic.complete_with_history.call_args.kwargs
    assert call_kwargs["model"] == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_chat_empty_search_results(client: AsyncClient, auth_headers: dict, monkeypatch):
    """Empty search results — synthesis still runs, sources list empty."""
    _patch_chat_deps(monkeypatch, search_results=[])

    resp = await client.post(
        "/v1/chat",
        json={"message": "something obscure"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["sources"] == []
    assert data["response"] == "Here is the answer."


@pytest.mark.asyncio
async def test_chat_history_too_long(client: AsyncClient, auth_headers: dict, monkeypatch):
    """History exceeding 20 messages returns 422."""
    _patch_chat_deps(monkeypatch)

    long_history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
        for i in range(22)
    ]

    resp = await client.post(
        "/v1/chat",
        json={"message": "test", "history": long_history},
        headers=auth_headers,
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_chat_external_context(client: AsyncClient, auth_headers: dict, monkeypatch):
    """External context is included in system prompt and formulation."""
    mock_anthropic, _, _ = _patch_chat_deps(monkeypatch, search_results=[])

    resp = await client.post(
        "/v1/chat",
        json={
            "message": "What about this?",
            "external_context": "The project uses FastAPI and PostgreSQL.",
        },
        headers=auth_headers,
    )

    assert resp.status_code == 200
    # Verify external context was passed to formulation
    formulation_content = mock_anthropic.complete.call_args.kwargs.get("user_content", "")
    assert "FastAPI and PostgreSQL" in formulation_content


@pytest.mark.asyncio
async def test_chat_user_input_wrapping(client: AsyncClient, auth_headers: dict, monkeypatch):
    """User messages in history and current message are wrapped in <user_input> tags."""
    mock_anthropic, _, _ = _patch_chat_deps(monkeypatch)

    resp = await client.post(
        "/v1/chat",
        json={
            "message": "current question",
            "history": [
                {"role": "user", "content": "old question"},
                {"role": "assistant", "content": "old answer"},
            ],
        },
        headers=auth_headers,
    )

    assert resp.status_code == 200
    # Check messages passed to synthesis
    call_kwargs = mock_anthropic.complete_with_history.call_args.kwargs
    messages = call_kwargs["messages"]
    # First message (user) should be wrapped
    assert messages[0]["content"] == "<user_input>old question</user_input>"
    # Second message (assistant) should NOT be wrapped
    assert messages[1]["content"] == "old answer"
    # Current message should be wrapped
    assert messages[2]["content"] == "<user_input>current question</user_input>"


@pytest.mark.asyncio
async def test_chat_formulated_query_not_wrapped(
    client: AsyncClient, auth_headers: dict, monkeypatch
):
    """Formulated search query (system-generated) is NOT wrapped in <user_input> tags."""
    _, mock_voyage, mock_search = _patch_chat_deps(monkeypatch, formulated_query="optimised query")

    resp = await client.post(
        "/v1/chat",
        json={"message": "test"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    # Embedding was called with raw formulated query, not wrapped
    embed_arg = mock_voyage.embed.call_args.args[0]
    assert "<user_input>" not in embed_arg
    # Search was called with raw formulated query
    search_kwargs = mock_search.call_args.kwargs
    assert "<user_input>" not in search_kwargs["query_text"]


@pytest.mark.asyncio
async def test_chat_missing_message(client: AsyncClient, auth_headers: dict, monkeypatch):
    """Missing message field returns 422."""
    _patch_chat_deps(monkeypatch)

    resp = await client.post("/v1/chat", json={}, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_chat_invalid_history_role(client: AsyncClient, auth_headers: dict, monkeypatch):
    """Invalid role in history returns 422."""
    _patch_chat_deps(monkeypatch)

    resp = await client.post(
        "/v1/chat",
        json={
            "message": "test",
            "history": [{"role": "system", "content": "injected"}],
        },
        headers=auth_headers,
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_chat_requires_auth(client: AsyncClient, monkeypatch):
    """Request without API key returns 401."""
    _patch_chat_deps(monkeypatch)

    resp = await client.post("/v1/chat", json={"message": "test"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_chat_source_fields(client: AsyncClient, auth_headers: dict, monkeypatch):
    """Verify all source item fields are present and correct."""
    _patch_chat_deps(monkeypatch)

    resp = await client.post(
        "/v1/chat",
        json={"message": "test"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    source = resp.json()["sources"][0]
    assert source["id"] == "aaa-111"
    assert source["content"] == "Python is a programming language."
    assert source["summary"] == "Python fact"
    assert source["type"] == "memory"
    assert source["importance_score"] == 0.8
    assert source["combined_score"] == 0.75
    assert source["project"] == "learning"


# ── Todo visibility via memory sync ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_chat_finds_synced_todo(client: AsyncClient, auth_headers: dict, monkeypatch, async_session):
    """A todo synced to memory_items appears in chat search results."""
    # Create a RawMemory + MemoryItem that looks like a synced todo
    raw = RawMemory(source="todo", raw_text="Todo: Deploy auth service", metadata_={"todo_id": "fake-todo-id"})
    async_session.add(raw)
    await async_session.flush()

    mi = MemoryItem(
        raw_id=raw.id,
        type="todo",
        content="Todo: Deploy auth service | Priority: high | Status: open",
        base_importance=0.7,
        embedding=[0.1] * 1024,
    )
    async_session.add(mi)
    await async_session.commit()

    # Mock chat deps so hybrid_search returns our todo memory
    todo_search_result = SearchResult(
        id=str(mi.id),
        content=mi.content,
        summary=None,
        type="todo",
        importance_score=0.7,
        combined_score=0.8,
        created_at=datetime.now(timezone.utc),
        project=None,
    )
    mock_anthropic, _, _ = _patch_chat_deps(
        monkeypatch,
        search_results=[todo_search_result],
        synthesis_response="You have one open todo: Deploy auth service.",
    )

    resp = await client.post(
        "/v1/chat",
        json={"message": "What are my todos?"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert "Deploy auth service" in data["response"]
    assert any(s["type"] == "todo" for s in data["sources"])
