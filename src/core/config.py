"""Configuration management for Open Brain."""

from pydantic import ConfigDict, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = ConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # Database — Supabase direct connection, port 5432. Required.
    # Set SQLALCHEMY_URL in .env (copy from .env.example)
    sqlalchemy_url: str

    # API
    api_key: SecretStr
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
    dead_letter_retry_limit: int = 3

    # Importance scoring
    importance_base_default: float = 0.5
    importance_recency_half_life_days: int = 30
    # Auto-captured sessions (source="claude-code") are background work noise.
    # Cap their base_importance so real intentional memories always rank higher.
    auto_capture_importance_ceiling: float = 0.4

    # Search
    search_default_limit: int = 10
    search_vector_weight: float = 0.5
    search_keyword_weight: float = 0.2
    search_importance_weight: float = 0.2
    search_recency_weight: float = 0.1

    # Context builder
    context_token_budget: int = 8192

    # Entity resolution
    entity_fuzzy_match_threshold: float = 0.92

    # Synthesis
    synthesis_max_memories_per_report: int = 50
    # NOTE: Haiku is used for MVP/demo cost savings.
    # Set SYNTHESIS_MODEL=claude-opus-4-6 in .env before going to production.
    synthesis_model: str = "claude-haiku-4-5-20251001"

    # Rate limiting (requests per minute per IP)
    rate_limit_memory_per_minute: int = 50
    rate_limit_search_per_minute: int = 100
    rate_limit_dead_letters_per_minute: int = 5

    # Discord integration (optional — leave blank to disable)
    discord_bot_token: SecretStr = SecretStr("")
    discord_allowed_user_ids: list[int] = []

    # Open Brain API URL (used by integrations to call the local API)
    open_brain_api_url: str = "http://localhost:8000"

    @field_validator("sqlalchemy_url")
    @classmethod
    def validate_sqlalchemy_url(cls, v: str) -> str:
        """Ensure database URL is set."""
        if not v or not v.strip():
            raise ValueError(
                "SQLALCHEMY_URL is required. Set it in .env or as an environment variable."
            )
        return v

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: SecretStr) -> SecretStr:
        """Ensure API key is set."""
        if not v or not v.get_secret_value().strip():
            raise ValueError("API_KEY is required. Set it in .env or as an environment variable.")
        return v

    @field_validator("embedding_dimensions")
    @classmethod
    def validate_embedding_dimensions(cls, v: int) -> int:
        """Validate embedding dimensions are valid for Voyage AI."""
        # Voyage supports specific dimensions (currently 1024)
        valid_dimensions = {1024}
        if v not in valid_dimensions:
            raise ValueError(f"embedding_dimensions must be one of {valid_dimensions}, got {v}")
        return v

    @field_validator(
        "search_vector_weight",
        "search_keyword_weight",
        "search_importance_weight",
        "search_recency_weight",
    )
    @classmethod
    def validate_search_weights(cls, v: float) -> float:
        """Validate search weights are between 0 and 1."""
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Search weights must be between 0 and 1, got {v}")
        return v

    @field_validator("entity_fuzzy_match_threshold")
    @classmethod
    def validate_fuzzy_threshold(cls, v: float) -> float:
        """Validate fuzzy match threshold is within [0.5, 1.0].

        Values below 0.5 cause excessive false-positive entity merges.
        """
        if not 0.5 <= v <= 1.0:
            raise ValueError(f"entity_fuzzy_match_threshold must be between 0.5 and 1.0, got {v}")
        return v

    @model_validator(mode="after")
    def validate_search_weights_sum(self) -> "Settings":
        """Ensure search weights sum to 1.0 (within ±0.001 tolerance)."""
        total = (
            self.search_vector_weight
            + self.search_keyword_weight
            + self.search_importance_weight
            + self.search_recency_weight
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                f"Search weights must sum to 1.0, got {total:.4f}. "
                f"Current: vector={self.search_vector_weight}, keyword={self.search_keyword_weight}, "
                f"importance={self.search_importance_weight}, recency={self.search_recency_weight}"
            )
        return self


# Module-level singleton instance (lazy initialization)
# Try to instantiate at import time, but gracefully handle missing env vars (useful for testing).
try:
    settings = Settings()
except Exception:
    settings = None  # type: ignore[assignment]
