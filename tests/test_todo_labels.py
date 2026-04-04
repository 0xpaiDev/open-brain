"""Tests for the Todo Label API endpoints.

Covers label CRUD, validation, duplicates, and auth.
"""

import pytest


# ── POST /v1/todo-labels ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_label(test_client, api_key_headers) -> None:
    """POST /v1/todo-labels with valid data returns 201."""
    resp = await test_client.post(
        "/v1/todo-labels",
        json={"name": "Work", "color": "#FF0000"},
        headers=api_key_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Work"
    assert body["color"] == "#FF0000"
    assert "id" in body


@pytest.mark.asyncio
async def test_create_label_default_color(test_client, api_key_headers) -> None:
    """POST without color uses default #6750A4."""
    resp = await test_client.post(
        "/v1/todo-labels",
        json={"name": "Personal"},
        headers=api_key_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["color"] == "#6750A4"


@pytest.mark.asyncio
async def test_create_label_duplicate_name_409(test_client, api_key_headers) -> None:
    """POST with duplicate name returns 409."""
    await test_client.post("/v1/todo-labels", json={"name": "Dup"}, headers=api_key_headers)
    resp = await test_client.post("/v1/todo-labels", json={"name": "Dup"}, headers=api_key_headers)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_label_empty_name_422(test_client, api_key_headers) -> None:
    """POST with empty name returns 422."""
    resp = await test_client.post("/v1/todo-labels", json={"name": ""}, headers=api_key_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_label_name_too_long_422(test_client, api_key_headers) -> None:
    """POST with name > 50 chars returns 422."""
    resp = await test_client.post(
        "/v1/todo-labels",
        json={"name": "x" * 51},
        headers=api_key_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_label_invalid_color_422(test_client, api_key_headers) -> None:
    """POST with non-hex color returns 422."""
    resp = await test_client.post(
        "/v1/todo-labels",
        json={"name": "Bad", "color": "red"},
        headers=api_key_headers,
    )
    assert resp.status_code == 422


# ── GET /v1/todo-labels ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_labels(test_client, api_key_headers) -> None:
    """GET /v1/todo-labels returns all created labels."""
    for name in ["Alpha", "Beta", "Gamma"]:
        await test_client.post("/v1/todo-labels", json={"name": name}, headers=api_key_headers)

    resp = await test_client.get("/v1/todo-labels", headers=api_key_headers)
    assert resp.status_code == 200
    labels = resp.json()
    assert len(labels) == 3
    assert {l["name"] for l in labels} == {"Alpha", "Beta", "Gamma"}


@pytest.mark.asyncio
async def test_list_labels_empty(test_client, api_key_headers) -> None:
    """GET /v1/todo-labels with no labels returns empty list."""
    resp = await test_client.get("/v1/todo-labels", headers=api_key_headers)
    assert resp.status_code == 200
    assert resp.json() == []


# ── DELETE /v1/todo-labels/{name} ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_label(test_client, api_key_headers) -> None:
    """DELETE removes the label, GET no longer returns it."""
    await test_client.post("/v1/todo-labels", json={"name": "Temp"}, headers=api_key_headers)
    resp = await test_client.delete("/v1/todo-labels/Temp", headers=api_key_headers)
    assert resp.status_code == 204

    labels = (await test_client.get("/v1/todo-labels", headers=api_key_headers)).json()
    assert len(labels) == 0


@pytest.mark.asyncio
async def test_delete_label_not_found_404(test_client, api_key_headers) -> None:
    """DELETE non-existent label returns 404."""
    resp = await test_client.delete("/v1/todo-labels/nonexistent", headers=api_key_headers)
    assert resp.status_code == 404


# ── Auth ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_label_endpoints_require_auth(test_client) -> None:
    """All label endpoints return 401 without X-API-Key."""
    assert (await test_client.get("/v1/todo-labels")).status_code == 401
    assert (await test_client.post("/v1/todo-labels", json={"name": "X"})).status_code == 401
    assert (await test_client.delete("/v1/todo-labels/X")).status_code == 401
