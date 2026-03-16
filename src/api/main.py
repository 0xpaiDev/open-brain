"""FastAPI application factory for Open Brain API."""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded

from src.api.middleware.auth import APIKeyMiddleware
from src.api.middleware.rate_limit import limiter, rate_limit_exceeded_handler
from src.api.routes.decisions import router as decisions_router
from src.api.routes.entities import router as entities_router
from src.api.routes.health import router as health_router
from src.api.routes.memory import router as memory_router
from src.api.routes.queue import router as queue_router
from src.api.routes.search import router as search_router
from src.api.routes.tasks import router as tasks_router
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

# Middleware (applied in reverse order — last added = outermost)
app.add_middleware(APIKeyMiddleware)

# Routes — tags appear as sections in /docs Swagger UI
app.include_router(health_router, tags=["Health"])
app.include_router(memory_router, tags=["Memory"])
app.include_router(search_router, tags=["Search"])
app.include_router(entities_router, tags=["Entities"])
app.include_router(tasks_router, tags=["Tasks"])
app.include_router(decisions_router, tags=["Decisions"])
app.include_router(queue_router, tags=["Queue"])
