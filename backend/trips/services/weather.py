"""Cached forecast lookups, keyed so that overlapping trips share results."""
from datetime import date

from django.conf import settings
from django.core.cache import cache

from ..domain.forecast_time import HourlySeries
from ..domain.geo import LatLon
from ..providers.base import WeatherProvider


def _key(point: LatLon, start: date, end: date) -> str:
    return f"wx:{point[0]:g}:{point[1]:g}:{start}:{end}"


def cached_forecast(
    provider: WeatherProvider, points: list[LatLon], start: date, end: date
) -> dict[LatLon, HourlySeries]:
    unique = list(dict.fromkeys(points))
    keys = {point: _key(point, start, end) for point in unique}
    found = cache.get_many(keys.values())
    result = {point: found[key] for point, key in keys.items() if key in found}
    missing = [point for point in unique if point not in result]
    if missing:
        fresh = provider.forecast(missing, start, end)
        cache.set_many(
            {keys[point]: series for point, series in fresh.items()},
            settings.WEATHER_CACHE_SECONDS,
        )
        result.update(fresh)
    return result
