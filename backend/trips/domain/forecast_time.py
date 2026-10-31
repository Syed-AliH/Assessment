"""Read an hourly forecast at an arbitrary moment.

Open-Meteo stamps variables differently. Wind speed is instantaneous at the
timestamp. Rain, snow and gusts describe the hour *ending* at the timestamp,
so 14:20 belongs to the 15:00 value, not the 14:00 one.
"""
from bisect import bisect_left
from dataclasses import dataclass


@dataclass(frozen=True)
class HourlySeries:
    """Parallel hourly lists. Times are ascending unix seconds."""

    times: list[int]
    wind_mph: list[float | None]
    gust_mph: list[float | None]
    rain_in: list[float | None]
    snow_in: list[float | None]


@dataclass(frozen=True)
class WeatherSample:
    wind_mph: float | None
    gust_mph: float | None
    rain_in_hr: float | None
    snow_in_hr: float | None


def _wind_at(series: HourlySeries, moment: float, after: int) -> float | None:
    end = series.wind_mph[after]
    if series.times[after] == moment:
        return end
    start = series.wind_mph[after - 1]
    if start is None or end is None:
        return None
    t0, t1 = series.times[after - 1], series.times[after]
    return start + (end - start) * (moment - t0) / (t1 - t0)


def sample_at(series: HourlySeries, moment: float) -> WeatherSample | None:
    """Forecast at `moment`, or None if it falls outside the series."""
    times = series.times
    if not times or moment > times[-1]:
        return None
    after = bisect_left(times, moment)  # first timestamp >= moment
    if after == 0 and times[0] != moment:
        return None
    return WeatherSample(
        wind_mph=_wind_at(series, moment, after),
        gust_mph=series.gust_mph[after],
        rain_in_hr=series.rain_in[after],
        snow_in_hr=series.snow_in[after],
    )
