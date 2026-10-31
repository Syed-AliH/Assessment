"""Risk on a grid around the trip, for each hour of the forecast slider."""
from ..domain.forecast_time import HourlySeries, sample_at
from ..domain.risk import classify
from .analyze import SLIDER_HOURS, load_record, parse_forecasts

UNKNOWN_CODE = "5"
HOUR_SECONDS = 3600


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


def build_heatmap(analysis_id: str, locations: list) -> dict:
    record = load_record(analysis_id)
    corridor = record["corridor"]
    forecasts = parse_forecasts(corridor.cells, locations)
    departure = record["departure"]
    return {
        "start": departure.isoformat(),
        "hours": SLIDER_HOURS,
        "step": corridor.step,
        "cells": [[lat, lon] for lat, lon in corridor.cells],
        "levels": [
            hourly_codes(forecasts.get(cell), departure.timestamp(), record["load_lb"])
            for cell in corridor.cells
        ],
    }
