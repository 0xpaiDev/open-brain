"""Tests for the Project Label API endpoints.

Covers label CRUD, validation, duplicates, and auth.
"""

import pytest

# ── POST /v1/project-labels ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_project_label(test_client, api_key_headers) -> None:
    """POST /v1/project-labels with valid data returns 201."""
    resp = await test_client.post(
        "/v1/project-labels",
        json={"name": "open-brain", "color": "#FF0000"},
        headers=api_key_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "open-brain"
    assert body["color"] == "#FF0000"
    assert "id" in body


@pytest.mark.asyncio
async def test_create_project_label_default_color(test_client, api_key_headers) -> None:
    """POST without color uses default #6750A4."""
    resp = await test_client.post(
        "/v1/project-labels",
        json={"name": "egle-climbing"},
        headers=api_key_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["color"] == "#6750A4"


@pytest.mark.asyncio
async def test_create_project_label_duplicate_name_409(test_client, api_key_headers) -> None:
    """POST with duplicate name returns 409."""
    await test_client.post("/v1/project-labels", json={"name": "Dup"}, headers=api_key_headers)
    resp = await test_client.post("/v1/project-labels", json={"name": "Dup"}, headers=api_key_headers)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_project_label_empty_name_422(test_client, api_key_headers) -> None:
    """POST with empty name returns 422."""
    resp = await test_client.post("/v1/project-labels", json={"name": ""}, headers=api_key_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_project_label_name_too_long_422(test_client, api_key_headers) -> None:
    """POST with name > 100 chars returns 422."""
    resp = await test_client.post(
        "/v1/project-labels",
        json={"name": "x" * 101},
        headers=api_key_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_project_label_invalid_color_422(test_client, api_key_headers) -> None:
    """POST with non-hex color returns 422."""
    resp = await test_client.post(
        "/v1/project-labels",
        json={"name": "Bad", "color": "red"},
        headers=api_key_headers,
    )
    assert resp.status_code == 422


# ── GET /v1/project-labels ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_project_labels(test_client, api_key_headers) -> None:
    """GET /v1/project-labels returns all created labels."""
    for name in ["Alpha", "Beta", "Gamma"]:
        await test_client.post("/v1/project-labels", json={"name": name}, headers=api_key_headers)

    resp = await test_client.get("/v1/project-labels", headers=api_key_headers)
    assert resp.status_code == 200
    labels = resp.json()
    assert len(labels) == 3
    assert {l["name"] for l in labels} == {"Alpha", "Beta", "Gamma"}


@pytest.mark.asyncio
async def test_list_project_labels_empty(test_client, api_key_headers) -> None:
    """GET /v1/project-labels with no labels returns empty list."""
    resp = await test_client.get("/v1/project-labels", headers=api_key_headers)
    assert resp.status_code == 200
    assert resp.json() == []


# ── DELETE /v1/project-labels/{name} ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_project_label(test_client, api_key_headers) -> None:
    """DELETE removes the label, GET no longer returns it."""
    await test_client.post("/v1/project-labels", json={"name": "Temp"}, headers=api_key_headers)
    resp = await test_client.delete("/v1/project-labels/Temp", headers=api_key_headers)
    assert resp.status_code == 204

    labels = (await test_client.get("/v1/project-labels", headers=api_key_headers)).json()
    assert len(labels) == 0


@pytest.mark.asyncio
async def test_delete_project_label_not_found_404(test_client, api_key_headers) -> None:
    """DELETE non-existent label returns 404."""
    resp = await test_client.delete("/v1/project-labels/nonexistent", headers=api_key_headers)
    assert resp.status_code == 404


# ── Auth ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_project_label_endpoints_require_auth(test_client) -> None:
    """All project label endpoints return 401 without X-API-Key."""
    assert (await test_client.get("/v1/project-labels")).status_code == 401
    assert (await test_client.post("/v1/project-labels", json={"name": "X"})).status_code == 401
    assert (await test_client.delete("/v1/project-labels/X")).status_code == 401


# ── Memory project field ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_ingest_with_project_metadata(test_client, api_key_headers) -> None:
    """POST /v1/memory with project in metadata stores it."""
    resp = await test_client.post(
        "/v1/memory",
        json={"text": "Test memory with project tag", "metadata": {"project": "open-brain"}},
        headers=api_key_headers,
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_memory_response_includes_project_field(test_client, api_key_headers) -> None:
    """GET /v1/memory/recent response items include project field."""
    resp = await test_client.get("/v1/memory/recent", headers=api_key_headers)
    assert resp.status_code == 200
    # Even with no items, the schema should be valid
    body = resp.json()
    assert "items" in body
    for item in body["items"]:
        assert "project" in item


@pytest.mark.asyncio
async def test_memory_recent_project_filter(test_client, api_key_headers) -> None:
    """GET /v1/memory/recent?project_filter=x filters correctly."""
    resp = await test_client.get(
        "/v1/memory/recent?project_filter=nonexistent-project",
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
