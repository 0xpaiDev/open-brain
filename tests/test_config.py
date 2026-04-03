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
            assert settings.api_key.get_secret_value() == "test-api-key"  # SecretStr

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
            assert settings.db_ssl_mode == "require"

    def test_sqlalchemy_url_is_required(self) -> None:
        """Settings should raise ValidationError when SQLALCHEMY_URL is missing."""
        with patch.dict(
            os.environ,
            {
                "ANTHROPIC_API_KEY": "sk-ant-test",
                "VOYAGE_API_KEY": "pa-test",
                "API_KEY": "test-key",
            },
            clear=False,
        ):
            # Remove SQLALCHEMY_URL if it exists
            if "SQLALCHEMY_URL" in os.environ:
                del os.environ["SQLALCHEMY_URL"]

            # _env_file=None prevents fallback to .env on disk (which may contain SQLALCHEMY_URL)
            with pytest.raises(ValidationError) as exc_info:
                Settings(_env_file=None)  # type: ignore[call-arg]
            assert "sqlalchemy_url" in str(exc_info.value).lower()

    def test_api_key_is_required(self) -> None:
        """Settings should raise ValidationError when API_KEY is missing."""
        with patch.dict(
            os.environ,
            {
                "SQLALCHEMY_URL": "postgresql+asyncpg://user:pass@localhost/db",
                "ANTHROPIC_API_KEY": "sk-ant-test",
                "VOYAGE_API_KEY": "pa-test",
            },
            clear=False,
        ):
            # Remove API_KEY if it exists
            if "API_KEY" in os.environ:
                del os.environ["API_KEY"]

            # _env_file=None prevents fallback to .env on disk (which may contain API_KEY)
            with pytest.raises(ValidationError) as exc_info:
                Settings(_env_file=None)  # type: ignore[call-arg]
            assert "api_key" in str(exc_info.value).lower()

    def test_search_weights_sum_to_one(self) -> None:
        """Search weights should sum to 1.0 (within tolerance)."""
        # Valid case: weights sum to 1.0
        with patch.dict(
            os.environ,
            {
                "SQLALCHEMY_URL": "postgresql+asyncpg://user:pass@localhost/db",
                "ANTHROPIC_API_KEY": "sk-ant-test",
                "VOYAGE_API_KEY": "pa-test",
                "API_KEY": "test-key",
                "SEARCH_VECTOR_WEIGHT": "0.5",
                "SEARCH_KEYWORD_WEIGHT": "0.2",
                "SEARCH_IMPORTANCE_WEIGHT": "0.2",
                "SEARCH_RECENCY_WEIGHT": "0.1",
            },
        ):
            settings = Settings()  # type: ignore[call-arg]
            assert settings.search_vector_weight == 0.5
            assert settings.search_keyword_weight == 0.2
            assert settings.search_importance_weight == 0.2
            assert settings.search_recency_weight == 0.1

        # Invalid case: weights don't sum to 1.0
        with patch.dict(
            os.environ,
            {
                "SQLALCHEMY_URL": "postgresql+asyncpg://user:pass@localhost/db",
                "ANTHROPIC_API_KEY": "sk-ant-test",
                "VOYAGE_API_KEY": "pa-test",
                "API_KEY": "test-key",
                "SEARCH_VECTOR_WEIGHT": "0.5",
                "SEARCH_KEYWORD_WEIGHT": "0.3",
                "SEARCH_IMPORTANCE_WEIGHT": "0.3",
                "SEARCH_RECENCY_WEIGHT": "0.2",  # Sum is 1.3
            },
        ):
            with pytest.raises(ValidationError) as exc_info:
                Settings()  # type: ignore[call-arg]
            assert "sum to 1.0" in str(exc_info.value)

    def test_api_key_not_in_repr(self) -> None:
        """api_key SecretStr must not expose raw value in repr or str (C2)."""
        with patch.dict(
            os.environ,
            {
                "SQLALCHEMY_URL": "postgresql+asyncpg://user:pass@localhost/db",
                "ANTHROPIC_API_KEY": "sk-ant-test",
                "VOYAGE_API_KEY": "pa-test",
                "API_KEY": "super-secret-api-key-12345",
            },
        ):
            settings = Settings()  # type: ignore[call-arg]
            r = repr(settings)
            assert "super-secret-api-key-12345" not in r
            assert str(settings.api_key) != "super-secret-api-key-12345"
            assert settings.api_key.get_secret_value() == "super-secret-api-key-12345"

    def test_fuzzy_threshold_rejects_below_range(self) -> None:
        """entity_fuzzy_match_threshold below 0.5 should raise ValidationError (L1)."""
        with patch.dict(
            os.environ,
            {
                "SQLALCHEMY_URL": "postgresql+asyncpg://user:pass@localhost/db",
                "API_KEY": "test-key",
                "ENTITY_FUZZY_MATCH_THRESHOLD": "0.3",
            },
        ):
            with pytest.raises(ValidationError) as exc_info:
                Settings(_env_file=None)  # type: ignore[call-arg]
            assert "0.5" in str(exc_info.value)

    def test_fuzzy_threshold_rejects_above_range(self) -> None:
        """entity_fuzzy_match_threshold above 1.0 should raise ValidationError (L1)."""
        with patch.dict(
            os.environ,
            {
                "SQLALCHEMY_URL": "postgresql+asyncpg://user:pass@localhost/db",
                "API_KEY": "test-key",
                "ENTITY_FUZZY_MATCH_THRESHOLD": "1.1",
            },
        ):
            with pytest.raises(ValidationError) as exc_info:
                Settings(_env_file=None)  # type: ignore[call-arg]
            assert "1.0" in str(exc_info.value)

    def test_fuzzy_threshold_accepts_valid_range(self) -> None:
        """entity_fuzzy_match_threshold within [0.5, 1.0] should be accepted (L1)."""
        with patch.dict(
            os.environ,
            {
                "SQLALCHEMY_URL": "postgresql+asyncpg://user:pass@localhost/db",
                "API_KEY": "test-key",
                "ENTITY_FUZZY_MATCH_THRESHOLD": "0.75",
            },
        ):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            assert settings.entity_fuzzy_match_threshold == 0.75

    def test_dashboard_origins_parses_comma_separated(self) -> None:
        """dashboard_origins splits comma-separated string into a list of origins."""
        with patch.dict(
            os.environ,
            {
                "SQLALCHEMY_URL": "postgresql+asyncpg://user:pass@localhost/db",
                "API_KEY": "test-key",
                "DASHBOARD_ORIGINS": "http://a, http://b , http://c",
            },
        ):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            origins = [o.strip() for o in settings.dashboard_origins.split(",") if o.strip()]
            assert origins == ["http://a", "http://b", "http://c"]

    def test_dashboard_origins_empty_string_yields_empty_list(self) -> None:
        """Empty dashboard_origins produces an empty list after split/filter."""
        with patch.dict(
            os.environ,
            {
                "SQLALCHEMY_URL": "postgresql+asyncpg://user:pass@localhost/db",
                "API_KEY": "test-key",
                "DASHBOARD_ORIGINS": "",
            },
        ):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            origins = [o.strip() for o in settings.dashboard_origins.split(",") if o.strip()]
            assert origins == []

    def test_dashboard_origins_defaults_empty_when_unset(self) -> None:
        """dashboard_origins defaults to empty string when env var is not set."""
        with patch.dict(
            os.environ,
            {
                "SQLALCHEMY_URL": "postgresql+asyncpg://user:pass@localhost/db",
                "API_KEY": "test-key",
            },
        ):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            assert settings.dashboard_origins == ""
