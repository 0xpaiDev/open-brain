"""Health check endpoints.

GET /health  — always 200, no auth required
GET /ready   — 200 if DB is reachable, 503 otherwise
"""

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.core.database import health_check

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """Liveness probe — always returns 200 while the process is running.

    Returns:
        200: {"status": "ok"}
    """
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> JSONResponse:
    """Readiness probe — returns 200 only if the database is reachable.

    Returns:
        200: {"status": "ok"}
        503: {"status": "error", "reason": "db_down"}
    """
    ok = await health_check()
    if ok:
        return JSONResponse(status_code=200, content={"status": "ok"})
    logger.warning("readiness_check_failed", reason="db_down")
    return JSONResponse(status_code=503, content={"status": "error", "reason": "db_down"})
