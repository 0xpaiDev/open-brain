"""Configuration management for Open Brain."""

from pydantic import ConfigDict, SecretStr, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = ConfigDict(env_file=".env", case_sensitive=False)

    # Database (Supabase direct connection, port 5432)
    sqlalchemy_url: str = "postgresql+asyncpg://postgres:changeme@localhost:5432/postgres"

    # API
    api_key: str = "test-secret-key"
    api_host: str = "localhost"
    api_port: int = 8000

    # LLM
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-haiku-4-5-20251001"

    # Embeddings
    voyage_api_key: SecretStr | None = None
    voyage_model: str = "voyage-3"
    embedding_dimensions: int = 1024

    # Application
    log_level: str = "info"
    environment: str = "development"

    # Worker
    worker_poll_interval: int = 5
    worker_lock_ttl_seconds: int = 300

    # Importance scoring
    importance_base_default: float = 0.5
    importance_recency_half_life_days: int = 30

    # Search
    search_default_limit: int = 10
    search_vector_weight: float = 0.5
    search_keyword_weight: float = 0.2
    search_importance_weight: float = 0.2
    search_recency_weight: float = 0.1

    # Entity resolution
    entity_fuzzy_match_threshold: float = 0.92

    # Synthesis
    synthesis_max_memories_per_report: int = 50

    @field_validator("embedding_dimensions")
    @classmethod
    def validate_embedding_dimensions(cls, v: int) -> int:
        """Validate embedding dimensions are valid for Voyage AI."""
        # Voyage supports specific dimensions (currently 1024)
        valid_dimensions = {1024}
        if v not in valid_dimensions:
            raise ValueError(f"embedding_dimensions must be one of {valid_dimensions}, got {v}")
        return v

    @field_validator("search_vector_weight", "search_keyword_weight", "search_importance_weight", "search_recency_weight")
    @classmethod
    def validate_search_weights(cls, v: float) -> float:
        """Validate search weights are between 0 and 1."""
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Search weights must be between 0 and 1, got {v}")
        return v


# Module-level singleton instance (lazy initialization)
try:
    settings = Settings()
except Exception:
    # Allow module import to succeed even if required vars are missing
    # (useful for testing and initial setup)
    settings = None  # type: ignore[assignment]
