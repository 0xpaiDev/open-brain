"""Tests for configuration module."""

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.core.config import Settings


class TestSettingsLoading:
    """Tests for Settings initialization and environment variable loading."""

    def test_settings_loads_from_env(self) -> None:
        """Settings should load successfully from environment variables."""
        with patch.dict(
            os.environ,
            {
                "SQLALCHEMY_URL": "postgresql+asyncpg://user:pass@localhost/db",
                "ANTHROPIC_API_KEY": "sk-ant-test-key",
                "VOYAGE_API_KEY": "pa-test-key",
                "API_KEY": "test-api-key",
            },
        ):
            settings = Settings()  # type: ignore[call-arg]
            assert settings.sqlalchemy_url == "postgresql+asyncpg://user:pass@localhost/db"
            assert str(settings.anthropic_api_key) != "sk-ant-test-key"  # SecretStr
            assert str(settings.voyage_api_key) != "pa-test-key"  # SecretStr
            assert settings.api_key == "test-api-key"

    def test_secret_str_not_logged(self) -> None:
        """SecretStr fields should not expose raw values in string representation."""
        with patch.dict(
            os.environ,
            {
                "SQLALCHEMY_URL": "postgresql+asyncpg://user:pass@localhost/db",
                "ANTHROPIC_API_KEY": "sk-ant-secret123",
                "VOYAGE_API_KEY": "pa-secret456",
                "API_KEY": "test-key",
            },
        ):
            settings = Settings()  # type: ignore[call-arg]
            # SecretStr should mask the value
            assert str(settings.anthropic_api_key) == "**********"
            assert str(settings.voyage_api_key) == "**********"
            # But .get_secret_value() should return the actual value
            assert settings.anthropic_api_key.get_secret_value() == "sk-ant-secret123"
            assert settings.voyage_api_key.get_secret_value() == "pa-secret456"

    def test_embedding_dimensions_validator(self) -> None:
        """Embedding dimensions should validate correctly."""
        # Valid dimension (default 1024)
        with patch.dict(
            os.environ,
            {
                "SQLALCHEMY_URL": "postgresql+asyncpg://user:pass@localhost/db",
                "ANTHROPIC_API_KEY": "sk-ant-test",
                "VOYAGE_API_KEY": "pa-test",
                "API_KEY": "test-key",
                "EMBEDDING_DIMENSIONS": "1024",
            },
        ):
            settings = Settings()  # type: ignore[call-arg]
            assert settings.embedding_dimensions == 1024

        # Invalid dimension (should raise)
        with patch.dict(
            os.environ,
            {
                "SQLALCHEMY_URL": "postgresql+asyncpg://user:pass@localhost/db",
                "ANTHROPIC_API_KEY": "sk-ant-test",
                "VOYAGE_API_KEY": "pa-test",
                "API_KEY": "test-key",
                "EMBEDDING_DIMENSIONS": "999",  # Not a valid Voyage dimension
            },
        ):
            with pytest.raises(ValidationError):
                Settings()  # type: ignore[call-arg]

    def test_default_values(self) -> None:
        """Settings should provide sensible defaults."""
        with patch.dict(
            os.environ,
            {
                "SQLALCHEMY_URL": "postgresql+asyncpg://user:pass@localhost/db",
                "ANTHROPIC_API_KEY": "sk-ant-test",
                "VOYAGE_API_KEY": "pa-test",
                "API_KEY": "test-key",
            },
        ):
            settings = Settings()  # type: ignore[call-arg]
            assert settings.embedding_dimensions == 1024
            assert settings.log_level == "info"
            assert settings.environment == "development"
            assert settings.api_port == 8000
