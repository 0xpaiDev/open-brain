"""Tests for database module."""

from unittest.mock import AsyncMock, patch

import pytest

from src.core.database import health_check


@pytest.mark.asyncio
async def test_health_check_fails_when_engine_none() -> None:
    """health_check should return False if async_engine is None."""
    with patch("src.core.database.async_engine", None):
        result = await health_check()
        assert result is False


@pytest.mark.asyncio
async def test_health_check_fails_on_connection_error() -> None:
    """health_check should return False if database is unreachable."""
    mock_engine = AsyncMock()
    mock_engine.connect.side_effect = Exception("Connection refused")

    with patch("src.core.database.async_engine", mock_engine):
        result = await health_check()
        assert result is False


@pytest.mark.asyncio
async def test_get_db_requires_initialization() -> None:
    """get_db should raise if database not initialized."""
    from src.core import database

    # Temporarily set AsyncSessionLocal to None
    with patch.object(database, "AsyncSessionLocal", None):
        gen = database.get_db()
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await gen.__anext__()
