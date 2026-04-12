"""Database connection and session management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Forward declaration — populated after init_db() so callers can do:
#   from src.core.database import get_db_context
#   async with get_db_context() as session: ...
from src.core.config import get_settings

async_engine: AsyncEngine | None = None
AsyncSessionLocal: sessionmaker[AsyncSession] | None = None


async def init_db() -> None:
    """Initialize database engine and session factory."""
    global async_engine, AsyncSessionLocal

    settings = get_settings()
    async_engine = create_async_engine(
        settings.sqlalchemy_url,
        echo=settings.log_level == "debug",
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=2,
        connect_args={
            "ssl": settings.db_ssl_mode,
            "statement_cache_size": 0,  # Required for Supabase Supavisor compatibility (prevents prepared statement conflicts)
        },
    )

    # Note: pgvector.asyncpg.register_vector is intentionally NOT used here.
    # pgvector.sqlalchemy.Vector.process_bind_param returns a text-format string
    # '[0.1,0.2,...]' which asyncpg sends as text; PostgreSQL casts it to vector.
    # Calling register_vector registers a codec that expects list[float] — this
    # conflicts with the string output of process_bind_param, causing DataError.

    AsyncSessionLocal = sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Async generator dependency for FastAPI's Depends()."""
    if AsyncSessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    async with AsyncSessionLocal() as session:
        yield session


# Context manager variant for use outside FastAPI (e.g. worker, CLI)
get_db_context = asynccontextmanager(get_db)


async def health_check() -> bool:
    """Check database connectivity."""
    if async_engine is None:
        return False

    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def close_db() -> None:
    """Close database connection pool."""
    global async_engine

    if async_engine is not None:
        await async_engine.dispose()
        async_engine = None
