"""Open Brain MCP Server.

Exposes three tools over stdio (standard MCP transport) so that any
MCP-capable AI (Claude, Gemini, OpenAI) can search and ingest memories.

Tools:
    search_memory   — Hybrid search; returns formatted result list.
    get_context     — Token-budgeted LLM-ready context block.
    ingest_memory   — Ingest text into the pipeline.

Configuration via environment variables:
    OPENBRAIN_API_URL  — Base URL of the Open Brain API (default: http://localhost:8000)
    OPENBRAIN_API_KEY  — X-API-Key header value

Run:
    python src/mcp_server.py
"""

import os

import httpx
from fastmcp import FastMCP

# ── Config ────────────────────────────────────────────────────────────────────

API_URL: str = os.environ.get("OPENBRAIN_API_URL", "http://localhost:8000").rstrip("/")
API_KEY: str = os.environ.get("OPENBRAIN_API_KEY", "")
TIMEOUT: float = 30.0

mcp: FastMCP = FastMCP(
    "open-brain",
    instructions=(
        "Access Shu's personal memory system. "
        "Use search_memory or get_context at the start of each conversation "
        "to retrieve relevant memories. Use ingest_memory to save important "
        "information after a session."
    ),
)


# ── Shared HTTP helpers ───────────────────────────────────────────────────────


def _headers() -> dict[str, str]:
    """Return auth headers for the Open Brain API."""
    return {"X-API-Key": API_KEY, "Content-Type": "application/json"}


def _get(path: str, params: dict[str, str | int]) -> httpx.Response:
    """Synchronous GET to the Open Brain API."""
    return httpx.get(
        f"{API_URL}{path}",
        params=params,
        headers=_headers(),
        timeout=TIMEOUT,
    )


def _post(path: str, body: dict[str, str]) -> httpx.Response:
    """Synchronous POST to the Open Brain API."""
    return httpx.post(
        f"{API_URL}{path}",
        json=body,
        headers=_headers(),
        timeout=TIMEOUT,
    )


# ── Tool implementations (pure functions — importable for testing) ─────────────


def _do_search_memory(query: str, limit: int) -> str:
    """Core logic for search_memory — returns formatted string."""
    if not query.strip():
        return "Error: query must not be empty."
    clamped = max(1, min(limit, 100))
    try:
        resp = _get("/v1/search", {"q": query, "limit": clamped})
    except httpx.ConnectError:
        return "Error: could not connect to Open Brain API. Is the server running?"
    except httpx.TimeoutException:
        return "Error: Open Brain API timed out."

    if resp.status_code == 401:
        return "Error: authentication failed — check OPENBRAIN_API_KEY."
    if resp.status_code != 200:
        return f"Error: API returned {resp.status_code}."

    data = resp.json()
    results = data.get("results", [])
    if not results:
        return "No results found."

    lines: list[str] = [f"Search results for '{query}' ({len(results)} items):\n"]
    for i, r in enumerate(results, 1):
        date_str = (r.get("created_at") or "")[:10] or "unknown"
        score = r.get("combined_score", 0.0)
        rtype = (r.get("type") or "memory").upper()
        content = r.get("content") or r.get("summary") or ""
        snippet = content[:200] + ("..." if len(content) > 200 else "")
        lines.append(f"[{i}] {rtype} | {date_str} | score={score:.3f}")
        lines.append(f"    {snippet}")
    return "\n".join(lines)


def _do_get_context(query: str, limit: int) -> str:
    """Core logic for get_context — returns LLM-ready context block."""
    if not query.strip():
        return "Error: query must not be empty."
    clamped = max(1, min(limit, 100))
    try:
        resp = _get("/v1/search/context", {"q": query, "limit": clamped})
    except httpx.ConnectError:
        return "Error: could not connect to Open Brain API. Is the server running?"
    except httpx.TimeoutException:
        return "Error: Open Brain API timed out."

    if resp.status_code == 401:
        return "Error: authentication failed — check OPENBRAIN_API_KEY."
    if resp.status_code != 200:
        return f"Error: API returned {resp.status_code}."

    data = resp.json()
    context: str = data.get("context", "")
    tokens_used: int = data.get("tokens_used", 0)
    tokens_budget: int = data.get("tokens_budget", 0)
    items_included: int = data.get("items_included", 0)

    if not context.strip():
        return "No relevant memories found for this query."

    footer = f"\n[Open Brain: {items_included} items, {tokens_used}/{tokens_budget} tokens]"
    return context + footer


def _do_ingest_memory(text: str, source: str) -> str:
    """Core logic for ingest_memory — returns status string."""
    if not text.strip():
        return "Error: text must not be empty."
    try:
        resp = _post("/v1/memory", {"text": text, "source": source})
    except httpx.ConnectError:
        return "Error: could not connect to Open Brain API. Is the server running?"
    except httpx.TimeoutException:
        return "Error: Open Brain API timed out."

    if resp.status_code == 401:
        return "Error: authentication failed — check OPENBRAIN_API_KEY."
    if resp.status_code == 422:
        detail = resp.json().get("detail", "invalid input")
        return f"Error: {detail}"
    if resp.status_code == 202:
        data = resp.json()
        raw_id = data.get("raw_id", "?")
        status = data.get("status", "queued")
        if status == "duplicate":
            return f"Duplicate: memory already ingested within 24h. raw_id={raw_id}"
        return f"Queued for processing. raw_id={raw_id}"
    return f"Error: API returned {resp.status_code}."


# ── MCP tool decorators ───────────────────────────────────────────────────────


@mcp.tool()
async def search_memory(query: str, limit: int = 10) -> str:
    """Search Open Brain memory using hybrid vector + keyword search.

    Args:
        query: Natural language search query.
        limit: Maximum number of results (1–100, default 10).

    Returns:
        Formatted list of matching memory items with date, type, and score.
    """
    return _do_search_memory(query, limit)


@mcp.tool()
async def get_context(query: str, limit: int = 10) -> str:
    """Retrieve an LLM-ready context block from Open Brain memory.

    Prefer this over search_memory when you want to inject memory into your
    reasoning — the result is pre-formatted and token-budgeted (8 192 tokens).

    Args:
        query: Natural language query to retrieve relevant context.
        limit: Maximum number of results to consider (1–100, default 10).

    Returns:
        Token-budgeted context string ready for use in a system prompt.
    """
    return _do_get_context(query, limit)


@mcp.tool()
async def ingest_memory(text: str, source: str = "mcp") -> str:
    """Ingest text into Open Brain memory for future retrieval.

    Use this at the end of a session to save important decisions, insights,
    or information. The text is processed asynchronously by the pipeline.

    Args:
        text: The content to save (plain text, any length).
        source: Label for provenance tracking (default: "mcp").

    Returns:
        Confirmation with raw_id, or an error message.
    """
    return _do_ingest_memory(text, source)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
