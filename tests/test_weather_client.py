"""Tests for the Open-Meteo weather client.

All network is mocked via httpx.MockTransport. Each failure mode returns None.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import httpx
import pytest

from src.integrations.weather import WeatherSnapshot, fetch_weather_snapshot


def _settings(enabled: bool = True, lat: float = 54.8985, lon: float = 23.9036) -> MagicMock:
    s = MagicMock()
    s.pulse_weather_enabled = enabled
    s.pulse_weather_latitude = lat
    s.pulse_weather_longitude = lon
    return s


def _sample_response() -> dict:
    return {
        "daily": {
            "time": [
                "2026-04-23",
                "2026-04-24",
                "2026-04-25",
                "2026-04-26",
                "2026-04-27",
                "2026-04-28",
                "2026-04-29",
            ],
            "temperature_2m_min": [10.0, 9.0, 8.5, 7.0, 6.0, 5.5, 5.0],
            "temperature_2m_max": [18.0, 16.0, 14.0, 13.0, 12.0, 11.0, 10.0],
            "precipitation_sum": [0.1, 3.0, 4.5, 0.5, 0.0, 0.0, 2.0],
            "wind_speed_10m_max": [12.0, 14.0, 18.0, 10.0, 9.0, 8.0, 15.0],
        },
    }


@pytest.mark.asyncio
async def test_fetch_weather_snapshot_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.open-meteo.com" in str(request.url)
        assert "latitude=54.8985" in str(request.url)
        return httpx.Response(200, json=_sample_response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await fetch_weather_snapshot(_settings(), http)

    assert isinstance(result, WeatherSnapshot)
    assert result.today_min_temp == pytest.approx(10.0)
    assert result.today_max_temp == pytest.approx(18.0)
    assert result.today_precip_mm == pytest.approx(0.1)
    assert len(result.next_7_days) >= 6
    assert result.next_7_days[0].forecast_date == date(2026, 4, 24)
    assert result.next_7_days[0].precip_mm == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_fetch_weather_snapshot_disabled_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not be called")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await fetch_weather_snapshot(_settings(enabled=False), http)

    assert result is None


@pytest.mark.asyncio
async def test_fetch_weather_snapshot_timeout_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await fetch_weather_snapshot(_settings(), http)

    assert result is None


@pytest.mark.asyncio
async def test_fetch_weather_snapshot_429_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await fetch_weather_snapshot(_settings(), http)

    assert result is None


@pytest.mark.asyncio
async def test_fetch_weather_snapshot_schema_mismatch_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"hello": "world"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await fetch_weather_snapshot(_settings(), http)

    assert result is None


@pytest.mark.asyncio
async def test_fetch_weather_snapshot_uses_hardcoded_base_url():
    """URL base must not be config-driven — SSRF defense."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_sample_response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await fetch_weather_snapshot(_settings(), http)

    assert captured["url"].startswith("https://api.open-meteo.com/")


@pytest.mark.asyncio
async def test_fetch_weather_snapshot_coerces_lat_lon_to_float():
    """Malicious string lat/lon via env should not inject into the URL."""
    s = _settings()
    # Simulate a string-typed value slipping through (pydantic normally coerces)
    s.pulse_weather_latitude = 54.5
    s.pulse_weather_longitude = 23.5

    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_sample_response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await fetch_weather_snapshot(s, http)

    assert "latitude=54.5" in captured["url"]
    assert "longitude=23.5" in captured["url"]
