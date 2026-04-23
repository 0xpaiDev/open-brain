"""Open-Meteo weather client (no API key).

Used by the morning-pulse `opportunity` detector. The base URL is hardcoded
(SSRF defense) and lat/long are forced through `float(...)` before URL
construction. All network failures return None; the caller treats that as
"no weather signal available" and falls through to the next detector.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

_OPEN_METEO_BASE = "https://api.open-meteo.com"
_REQUEST_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class DayForecast:
    forecast_date: date
    min_temp: float
    max_temp: float
    precip_mm: float
    wind_kmh: float


@dataclass(frozen=True)
class WeatherSnapshot:
    today_min_temp: float
    today_max_temp: float
    today_precip_mm: float
    today_wind_kmh: float
    next_7_days: list[DayForecast]


def _parse_response(data: dict[str, Any]) -> WeatherSnapshot | None:
    daily = data.get("daily")
    if not isinstance(daily, dict):
        return None

    try:
        times = daily["time"]
        tmin = daily["temperature_2m_min"]
        tmax = daily["temperature_2m_max"]
        precip = daily["precipitation_sum"]
        wind = daily["wind_speed_10m_max"]
    except KeyError:
        return None

    if not isinstance(times, list) or len(times) == 0:
        return None
    lists = [tmin, tmax, precip, wind]
    if any(not isinstance(x, list) for x in lists):
        return None
    if any(len(x) != len(times) for x in lists):
        return None

    try:
        next_days: list[DayForecast] = []
        for i in range(1, len(times)):
            next_days.append(
                DayForecast(
                    forecast_date=date.fromisoformat(str(times[i])),
                    min_temp=float(tmin[i]),
                    max_temp=float(tmax[i]),
                    precip_mm=float(precip[i]),
                    wind_kmh=float(wind[i]),
                )
            )
        return WeatherSnapshot(
            today_min_temp=float(tmin[0]),
            today_max_temp=float(tmax[0]),
            today_precip_mm=float(precip[0]),
            today_wind_kmh=float(wind[0]),
            next_7_days=next_days,
        )
    except (TypeError, ValueError):
        return None


async def fetch_weather_snapshot(
    settings: Any, http: httpx.AsyncClient
) -> WeatherSnapshot | None:
    """Fetch today's weather + 7-day forecast for the configured coordinates.

    Returns None on any failure (disabled, timeout, non-200, schema mismatch).
    """
    if not getattr(settings, "pulse_weather_enabled", False):
        return None

    lat = float(getattr(settings, "pulse_weather_latitude", 0.0))
    lon = float(getattr(settings, "pulse_weather_longitude", 0.0))

    url = f"{_OPEN_METEO_BASE}/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_min,temperature_2m_max,precipitation_sum,wind_speed_10m_max",
        "timezone": "UTC",
        "forecast_days": 7,
    }

    try:
        resp = await http.get(url, params=params, timeout=_REQUEST_TIMEOUT_SECONDS)
    except (httpx.RequestError, httpx.HTTPError):
        logger.warning("weather_fetch_request_failed")
        return None

    if resp.status_code != 200:
        logger.warning("weather_fetch_non_200", status=resp.status_code)
        return None

    try:
        data = resp.json()
    except ValueError:
        logger.warning("weather_fetch_invalid_json")
        return None

    snapshot = _parse_response(data)
    if snapshot is None:
        logger.warning("weather_fetch_schema_mismatch")
    return snapshot
