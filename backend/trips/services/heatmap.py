"""Risk on a grid around the trip, for each hour of the forecast slider."""
from django.conf import settings
from django.core.cache import cache

from ..domain.corridor import build_corridor
from ..domain.forecast_time import HourlySeries, sample_at
from ..domain.geo import simplify
from ..domain.risk import classify
from ..providers.base import WeatherProvider
from .analyze import GEOMETRY_TOLERANCE_DEGREES, SLIDER_HOURS
from .weather import cached_forecast

UNKNOWN_CODE = "5"
HOUR_SECONDS = 3600


class AnalysisExpired(Exception):
    pass


def hourly_codes(series: HourlySeries | None, start: float, load_lb: float) -> str:
    """One digit per slider hour: 0-4 is the risk level, 5 is unknown."""
    if series is None:
        return UNKNOWN_CODE * (SLIDER_HOURS + 1)
    codes = []
    for hour in range(SLIDER_HOURS + 1):
        sample = sample_at(series, start + hour * HOUR_SECONDS)
        level = (
            classify(sample.wind_mph, sample.rain_in_hr, sample.snow_in_hr, load_lb).level
            if sample
            else None
        )
        codes.append(UNKNOWN_CODE if level is None else str(int(level)))
    return "".join(codes)


def build_heatmap(analysis_id: str, weather: WeatherProvider) -> dict:
    record = cache.get(f"analysis:{analysis_id}")
    if record is None:
        raise AnalysisExpired(analysis_id)

    corridor = build_corridor([
        simplify(points, GEOMETRY_TOLERANCE_DEGREES) for points in record["routes"]
    ])
    forecasts = cached_forecast(weather, corridor.cells, *record["window"])
    start = record["departure_utc"].timestamp()
    return {
        "start": record["departure_utc"].isoformat().replace("+00:00", "Z"),
        "hours": SLIDER_HOURS,
        "step": corridor.step,
        "cells": [[lat, lon] for lat, lon in corridor.cells],
        "levels": [
            hourly_codes(forecasts.get(cell), start, record["load_lb"])
            for cell in corridor.cells
        ],
    }


def cached_heatmap(analysis_id: str, weather: WeatherProvider) -> dict:
    key = f"heatmap:{analysis_id}"
    payload = cache.get(key)
    if payload is None:
        payload = build_heatmap(analysis_id, weather)
        cache.set(key, payload, settings.ANALYSIS_CACHE_SECONDS)
    return payload
