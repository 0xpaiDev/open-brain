"""Rate limiting middleware for Open Brain API.

Uses slowapi (Starlette-compatible wrapper around limits library).
Limits are configurable via environment variables (see config.py).

Default limits:
  POST /v1/memory          — 50 req/minute per IP
  GET  /v1/search          — 100 req/minute per IP
  POST /v1/dead-letters/*  — 5 req/minute per IP

All routes that are not explicitly limited fall back to FastAPI default (unlimited).
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return 429 with Retry-After header and JSON error body."""
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"},
        headers={"Retry-After": "60"},
    )


def _get_memory_rate() -> str:
    from src.core import config

    s = config.settings
    if s is None:
        return "50/minute"
    return f"{s.rate_limit_memory_per_minute}/minute"


def _get_search_rate() -> str:
    from src.core import config

    s = config.settings
    if s is None:
        return "100/minute"
    return f"{s.rate_limit_search_per_minute}/minute"


def _get_dead_letters_rate() -> str:
    from src.core import config

    s = config.settings
    if s is None:
        return "5/minute"
    return f"{s.rate_limit_dead_letters_per_minute}/minute"


# Module-level limiter — shared across all routes that import it.
# key_func=get_remote_address uses the client IP (or X-Forwarded-For when
# --proxy-headers is active, which we enable in docker-compose.yml).
limiter = Limiter(key_func=get_remote_address)

# Expose limit-string callables for use as route decorators.
memory_limit = _get_memory_rate
search_limit = _get_search_rate
dead_letters_limit = _get_dead_letters_rate
