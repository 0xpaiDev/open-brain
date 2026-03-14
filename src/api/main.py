"""FastAPI application factory for Open Brain API."""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from src.api.middleware.auth import APIKeyMiddleware
from src.api.routes.health import router as health_router
from src.api.routes.memory import router as memory_router
from src.api.routes.search import router as search_router
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

# Middleware (applied in reverse order — last added = outermost)
app.add_middleware(APIKeyMiddleware)

# Routes
app.include_router(health_router)
app.include_router(memory_router)
app.include_router(search_router)
