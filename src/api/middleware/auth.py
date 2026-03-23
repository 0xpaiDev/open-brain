"""X-API-Key authentication middleware.

Validates the X-API-Key header on all /v1/* routes.
Public paths (/health, /ready) are exempt from auth.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Paths that do not require authentication
_PUBLIC_PATHS = {"/health", "/ready"}


def _get_api_key() -> str:
    """Return the configured API key, instantiating settings on demand.

    settings may be None at import time when tests run without a .env file.
    Reading it inside the request handler ensures env vars set by test fixtures
    are available when the Settings() object is created.
    """
    from src.core import config

    if config.settings is None:
        config.settings = config.Settings()
    return config.settings.api_key.get_secret_value()


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Reject requests to /v1/* that are missing or have an invalid X-API-Key."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        api_key = request.headers.get("X-API-Key")
        if not api_key or api_key != _get_api_key():
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing X-API-Key"},
            )

        return await call_next(request)
