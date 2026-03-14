"""Database connection and session management."""

from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.config import settings


async_engine: AsyncEngine | None = None
AsyncSessionLocal: sessionmaker[AsyncSession] | None = None


async def init_db() -> None:
    """Initialize database engine and session factory."""
    global async_engine, AsyncSessionLocal

    async_engine = create_async_engine(
        settings.sqlalchemy_url,
        echo=settings.log_level == "debug",
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=2,
        connect_args={
            "ssl": "require",  # Supabase requires SSL
            "statement_cache_size": 0,  # Required for Supabase Supavisor compatibility (prevents prepared statement conflicts)
        },
    )

    AsyncSessionLocal = sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency: get database session."""
    if AsyncSessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    async with AsyncSessionLocal() as session:
        yield session


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
