"""Open-Meteo hourly forecasts.

Visitors' browsers download these, so that each spends their own quota. This
module says what to ask for and reads what comes back, with every unit
conversion in one place. Submitted data is checked as carefully as a vendor
response: a location that fails reads as missing, never as calm.
"""
from datetime import date, timedelta
from numbers import Real

from ..domain.forecast_time import HourlySeries

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY = "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"
MAX_FORECAST_DAYS = 16
MM_PER_INCH = 25.4
CM_PER_INCH = 2.54


def forecast_request(start: date, end: date) -> dict:
    return {
        "url": FORECAST_URL,
        "params": {
            "hourly": HOURLY,
            "wind_speed_unit": "mph",
            "timeformat": "unixtime",
            "timezone": "GMT",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
    }


def _is_number(value) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _sum_or_none(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a + b


def _scaled(values: list[float | None], divisor: float) -> list[float | None]:
    return [None if value is None else value / divisor for value in values]


def parse_location(raw: dict) -> HourlySeries | None:
    try:
        hourly = raw["hourly"]
        times = hourly["time"]
        columns = [hourly[name] for name in HOURLY.split(",")]
    except (KeyError, TypeError):
        return None
    if not isinstance(times, list) or not times or not all(_is_number(t) for t in times):
        return None
    if any(later <= earlier for earlier, later in zip(times, times[1:])):
        return None
    for column in columns:
        if not isinstance(column, list) or len(column) != len(times):
            return None
        if not all(value is None or _is_number(value) for value in column):
            return None
    wind, gust, rain, showers, snow = columns
    return HourlySeries(
        times=times,
        wind_mph=wind,
        gust_mph=gust,
        rain_in=_scaled([_sum_or_none(a, b) for a, b in zip(rain, showers)], MM_PER_INCH),
        snow_in=_scaled(snow, CM_PER_INCH),
    )


def clamp_range(start: date, end: date, today: date) -> tuple[date, date] | None:
    """Trim to the forecast window. None if nothing is left."""
    last = today + timedelta(days=MAX_FORECAST_DAYS - 1)
    start, end = max(start, today), min(end, last)
    return (start, end) if start <= end else None
