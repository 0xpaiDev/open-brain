"""Shared pure helpers for the Open Brain Discord integration.

All functions here are testable without Discord objects.
Modules and the main bot loader import from here.
"""

from typing import Any

import httpx
import structlog
from discord import Interaction

logger = structlog.get_logger()


def _get_settings() -> Any:
    """Lazy-load settings singleton (mirrors pattern in auth.py / ranking.py)."""
    from src.core import config

    if config.settings is None:
        config.settings = config.Settings()
    return config.settings


def require_allowed_user(interaction: Interaction, settings: Any) -> bool:
    """Return True if the interaction user is in discord_allowed_user_ids.

    Sends an ephemeral 'Not authorised.' response and returns False if not allowed.
    Callers should return immediately if this returns False.
    """
    if interaction.user.id not in settings.discord_allowed_user_ids:
        return False
    return True


# ── Pure business-logic helpers (testable without Discord objects) ─────────────


async def ingest_memory(
    http: httpx.AsyncClient,
    raw_text: str,
    author_id: str,
    channel_id: str,
    api_key: str,
    api_base_url: str,
) -> tuple[str, str]:
    """POST /v1/memory and return (raw_id, status).

    status is "queued" for newly enqueued memories, or "duplicate" when the
    same content was already ingested within the last 24 hours.

    Raises:
        httpx.HTTPStatusError: if the API returns a non-2xx status.
    """
    response = await http.post(
        f"{api_base_url}/v1/memory",
        json={
            "source": "discord",
            "text": raw_text,
            "metadata": {"channel_id": channel_id, "author_id": author_id},
        },
        headers={"X-API-Key": api_key},
    )
    response.raise_for_status()
    body = response.json()
    return str(body["raw_id"]), str(body.get("status", "queued"))


async def search_memories(
    http: httpx.AsyncClient,
    query: str,
    limit: int,
    api_key: str,
    api_base_url: str,
) -> list[dict[str, Any]]:
    """GET /v1/search and return the results list.

    Raises:
        httpx.HTTPStatusError: if the API returns a non-2xx status.
    """
    response = await http.get(
        f"{api_base_url}/v1/search",
        params={"q": query, "limit": limit},
        headers={"X-API-Key": api_key},
    )
    response.raise_for_status()
    data = response.json()
    # API returns {"results": [...]} wrapper
    if isinstance(data, dict):
        return list(data.get("results", []))
    return list(data)  # type: ignore[no-any-return]


async def trigger_digest(
    http: httpx.AsyncClient,
    days: int,
    api_key: str,
    api_base_url: str,
) -> dict[str, Any]:
    """POST /v1/synthesis/run and return the response dict.

    Args:
        http: httpx async client
        days: Number of days to synthesize (1–90)
        api_key: Open Brain API key
        api_base_url: Base URL of the Open Brain API

    Returns:
        Response dict with synthesis_id, memory_count, date_from, date_to, skipped, message

    Raises:
        httpx.HTTPStatusError: if the API returns a non-2xx status.
    """
    response = await http.post(
        f"{api_base_url}/v1/synthesis/run",
        json={"days": days},
        headers={"X-API-Key": api_key},
    )
    response.raise_for_status()
    return dict(response.json())


async def get_api_health(
    http: httpx.AsyncClient,
    api_base_url: str,
) -> bool:
    """Return True if the API /ready endpoint returns 200."""
    try:
        response = await http.get(f"{api_base_url}/ready")
        return response.status_code == 200
    except httpx.RequestError:
        return False
