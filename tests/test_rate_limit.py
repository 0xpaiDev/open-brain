"""Tests for rate limiting middleware.

Verifies:
- Limiter is registered in app.state
- Rate-limited routes enforce limits (429 after threshold)
- 429 response includes Retry-After header
- Unlimited routes (health, entities) are unaffected by rate limit config
"""

import pytest

from src.api.middleware.rate_limit import limiter


@pytest.fixture(autouse=False)
def reset_limiter_storage():
    """Reset in-memory rate limiter storage and re-enable limiter for isolation.

    The global set_test_env fixture disables the limiter (limiter.enabled=False)
    so that ordinary test suites don't hit 429s. Rate-limit tests must opt back
    in explicitly by using this fixture, which re-enables and then cleans up.
    """
    limiter.enabled = True
    limiter._limiter.storage.reset()
    yield
    limiter._limiter.storage.reset()
    limiter.enabled = False


@pytest.mark.asyncio
async def test_limiter_registered_in_app_state():
    """App state must hold the module-level limiter instance."""
    from src.api.main import app

    assert app.state.limiter is limiter


@pytest.mark.asyncio
async def test_memory_route_429_on_limit_exceeded(
    test_client, api_key_headers, monkeypatch, reset_limiter_storage
):
    """POST /v1/memory returns 429 once per-minute cap is reached."""
    monkeypatch.setenv("RATE_LIMIT_MEMORY_PER_MINUTE", "1")
    from src.core import config as _config

    monkeypatch.setattr(_config, "settings", _config.Settings())

    body = {"text": "first memory"}

    r1 = await test_client.post("/v1/memory", json=body, headers=api_key_headers)
    # First request should succeed (202 or 200 for duplicate)
    assert r1.status_code in (202, 200)

    r2 = await test_client.post("/v1/memory", json={"text": "second memory"}, headers=api_key_headers)
    assert r2.status_code == 429


@pytest.mark.asyncio
async def test_429_response_includes_retry_after_header(
    test_client, api_key_headers, monkeypatch, reset_limiter_storage
):
    """429 response must include a Retry-After header."""
    monkeypatch.setenv("RATE_LIMIT_MEMORY_PER_MINUTE", "1")
    from src.core import config as _config

    monkeypatch.setattr(_config, "settings", _config.Settings())

    await test_client.post("/v1/memory", json={"text": "first"}, headers=api_key_headers)

    r = await test_client.post("/v1/memory", json={"text": "second"}, headers=api_key_headers)
    assert r.status_code == 429
    # slowapi sets Retry-After on 429 responses
    assert "retry-after" in r.headers


@pytest.mark.asyncio
async def test_dead_letters_retry_429_on_limit_exceeded(
    test_client, api_key_headers, monkeypatch, reset_limiter_storage
):
    """POST /v1/dead-letters/{id}/retry returns 429 after threshold."""
    monkeypatch.setenv("RATE_LIMIT_DEAD_LETTERS_PER_MINUTE", "1")
    from src.core import config as _config

    monkeypatch.setattr(_config, "settings", _config.Settings())

    # Use a non-existent UUID — the rate limit fires before DB lookup on the 2nd request
    import uuid

    fake_id = str(uuid.uuid4())

    # First request: rate limit allows it (though 404 for unknown ID)
    r1 = await test_client.post(
        f"/v1/dead-letters/{fake_id}/retry", headers=api_key_headers
    )
    assert r1.status_code in (404, 429)  # 404 if within limit, 429 if already exceeded

    if r1.status_code == 404:
        # Confirm second request is rate limited
        r2 = await test_client.post(
            f"/v1/dead-letters/{fake_id}/retry", headers=api_key_headers
        )
        assert r2.status_code == 429


@pytest.mark.asyncio
async def test_health_endpoint_not_rate_limited(test_client, reset_limiter_storage):
    """GET /health is not rate limited — must always return 200."""
    for _ in range(5):
        r = await test_client.get("/health")
        assert r.status_code == 200
