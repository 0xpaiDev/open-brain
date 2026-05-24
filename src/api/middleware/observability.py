"""HTTP observability middleware — opens a Trace for every /v1/* request."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.observability import start_trace


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not request.url.path.startswith("/v1/"):
            return await call_next(request)
        async with start_trace(
            trigger_type="http",
            trigger_name=request.url.path,
            trigger_metadata={"method": request.method, "path": request.url.path},
        ):
            return await call_next(request)
