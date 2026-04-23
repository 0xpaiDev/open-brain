from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ── Environment setup ────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def set_test_env(monkeypatch):
    """Auto-use fixture to set required test environment variables.

    Re-initializes the config.settings singleton from the test env vars so
    that all tests see API_KEY='test-secret-key', not the value from .env.
    monkeypatch restores the original singleton after each test.

    Also disables the rate limiter so that test suites with many requests
    (e.g. test_todos.py with 50+ tests) do not hit 429 responses.
    """
    monkeypatch.setenv("SQLALCHEMY_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("API_KEY", "test-secret-key")
    # Default to legacy pulse path in tests; new signal-driven tests opt in explicitly.
    monkeypatch.setenv("PULSE_SIGNAL_DETECTORS", "")
    from src.core import config as _config
    monkeypatch.setattr(_config, "settings", _config.Settings())

    from src.api.middleware.rate_limit import limiter
    monkeypatch.setattr(limiter, "enabled", False)


# ── Database fixtures ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def async_engine():
    """In-memory SQLite DB with full schema.

    NOTE: SQLite does not enforce pgvector/UUID/JSONB types correctly.
    This is suitable for unit tests only. For integration tests, use a real
    Supabase test database or testcontainers PostgreSQL container.
    """
    from src.core.models import Base  # deferred: src not required at import time

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    # Enable FK enforcement in SQLite (disabled by default)
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """AsyncSession scoped to each test."""
    factory = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


# ── Mocked LLM clients ────────────────────────────────────────────────────────

@pytest.fixture
def mock_anthropic_client() -> AsyncMock:
    """AsyncMock of Anthropic client returning valid JSON extraction."""
    mock = AsyncMock()
    mock.messages.create.return_value = MagicMock(
        content=[MagicMock(text='{"type": "context", "content": "test", "entities": [], "decisions": [], "tasks": []}')]
    )
    return mock


@pytest.fixture
def mock_voyage_client() -> MagicMock:
    """MagicMock of Voyage AI client returning 1024-dim vector."""
    mock = MagicMock()
    mock.embed.return_value = MagicMock(embeddings=[[0.1] * 1024])
    return mock


# ── FastAPI test client ────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def test_client(async_session: AsyncSession):
    """Async test client with DB dependency overridden to use test session.

    NOTE: This fixture requires src/api/ to be implemented. Currently,
    src/api/ does not exist (Phase 1 Checkpoint 5+). Tests using this
    fixture will be skipped until the API module is created.
    """
    try:
        from httpx import ASGITransport, AsyncClient

        from src.api.main import app  # deferred
        from src.core.database import get_db  # deferred
    except ImportError as e:
        pytest.skip(f"API module not implemented yet: {e}")

    async def override_get_db():
        yield async_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


# ── Auth helpers ──────────────────────────────────────────────────────────────

@pytest.fixture
def api_key_headers() -> dict:
    """Standard auth headers for test requests."""
    return {"X-API-Key": "test-secret-key"}
