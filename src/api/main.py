"""FastAPI application factory for Open Brain API."""

from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from slowapi.errors import RateLimitExceeded

from src.api.middleware.auth import APIKeyMiddleware
from src.api.middleware.rate_limit import limiter, rate_limit_exceeded_handler
from src.api.routes.calendar_api import router as calendar_router
from src.api.routes.chat import router as chat_router
from src.api.routes.decisions import router as decisions_router
from src.api.routes.entities import router as entities_router
from src.api.routes.health import router as health_router
from src.api.routes.jobs import router as jobs_router
from src.api.routes.memory import router as memory_router
from src.api.routes.pulse import router as pulse_router
from src.api.routes.queue import router as queue_router
from src.api.routes.search import router as search_router
from src.api.routes.tasks import router as tasks_router
from src.api.routes.project_labels import router as project_labels_router
from src.api.routes.todo_labels import router as todo_labels_router
from src.api.routes.todos import router as todos_router
from src.core.config import get_settings
from src.core.database import close_db, init_db

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and tear down the database connection pool."""
    await init_db()
    logger.info("database_initialized")
    yield
    await close_db()
    logger.info("database_closed")


app = FastAPI(title="Open Brain", version="0.1.0", lifespan=lifespan)

# Rate limiter state — must be set before routes handle requests
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


@app.middleware("http")
async def add_security_headers(request: Request, call_next: Any) -> Response:
    """Inject security headers on every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


# Middleware (applied in reverse order — last added = outermost)
app.add_middleware(APIKeyMiddleware)

# CORS: allow dashboard origins when configured, otherwise block all.
def _cors_origins() -> list[str]:
    try:
        raw = get_settings().dashboard_origins
    except Exception:
        return []
    return [o.strip() for o in raw.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["X-API-Key", "Content-Type"],
)

# Routes — tags appear as sections in /docs Swagger UI
app.include_router(health_router, tags=["Health"])
app.include_router(memory_router, tags=["Memory"])
app.include_router(search_router, tags=["Search"])
app.include_router(entities_router, tags=["Entities"])
app.include_router(tasks_router, tags=["Tasks"])
app.include_router(decisions_router, tags=["Decisions"])
app.include_router(queue_router, tags=["Queue"])
app.include_router(todos_router, tags=["Todos"])
app.include_router(todo_labels_router, tags=["TodoLabels"])
app.include_router(project_labels_router, tags=["ProjectLabels"])
app.include_router(pulse_router, tags=["Pulse"])
app.include_router(jobs_router, tags=["Jobs"])
app.include_router(calendar_router, tags=["Calendar"])
app.include_router(chat_router, tags=["Chat"])
