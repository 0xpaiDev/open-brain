"""Tests for CORS middleware configuration.

Verifies that dashboard_origins are correctly parsed and applied by
CORSMiddleware: allowed origins get ACAO headers, disallowed origins
are blocked, and preflight OPTIONS requests return correct headers.

NOTE: CORS origins are frozen at app-creation time.  We build a minimal
ASGI app per-test to isolate from other tests that import the shared
``app`` singleton before DASHBOARD_ORIGINS is set.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


def _make_cors_app(origins: str):
    """Build a fresh FastAPI app with the given dashboard_origins."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI()

    parsed = [o.strip() for o in origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=parsed,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["X-API-Key", "Content-Type"],
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/v1/todos")
    async def stub_todos():
        return {"todos": [], "total": 0}

    return app


@pytest_asyncio.fixture
async def cors_client():
    """Test client for a fresh app with known CORS origins."""
    app = _make_cors_app("http://localhost:3000,https://dash.example.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── Allowed origin ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cors_allowed_origin_gets_acao_header(cors_client) -> None:
    """Request with an allowed Origin receives Access-Control-Allow-Origin."""
    resp = await cors_client.get(
        "/health",
        headers={"Origin": "http://localhost:3000"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


@pytest.mark.asyncio
async def test_cors_second_allowed_origin(cors_client) -> None:
    """Second comma-separated origin is also allowed."""
    resp = await cors_client.get(
        "/health",
        headers={"Origin": "https://dash.example.com"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://dash.example.com"


# ── Disallowed origin ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cors_disallowed_origin_no_acao_header(cors_client) -> None:
    """Request with an unlisted Origin does not receive ACAO header."""
    resp = await cors_client.get(
        "/health",
        headers={"Origin": "http://evil.com"},
    )
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


# ── Preflight OPTIONS ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cors_preflight_returns_allowed_methods(cors_client) -> None:
    """OPTIONS preflight with allowed Origin returns correct methods and headers."""
    resp = await cors_client.options(
        "/v1/todos",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "X-API-Key",
        },
    )
    assert resp.status_code == 200
    assert "PATCH" in resp.headers.get("access-control-allow-methods", "")
    assert "X-API-Key" in resp.headers.get("access-control-allow-headers", "")


# ── Empty origins ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cors_empty_origins_blocks_all() -> None:
    """When dashboard_origins is empty, no origin gets ACAO header."""
    app = _make_cors_app("")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/health",
            headers={"Origin": "http://localhost:3000"},
        )
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers
