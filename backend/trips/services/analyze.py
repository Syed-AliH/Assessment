"""Run a trip in two steps, with the visitor's browser fetching weather between.

`plan_trip` finds the routes and says which forecasts are needed. The browser
downloads them, so that each visitor spends their own weather quota rather
than one shared server allowance. `assess_trip` then does all of the risk work
here, on those forecasts.
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from django.conf import settings
from django.core.cache import cache

from ..domain.corridor import build_corridor
from ..domain.forecast_time import HourlySeries, WeatherSample, sample_at
from ..domain.geo import (
    MILES_PER_DEGREE_LAT,
    LatLon,
    coarsest_needed_step,
    simplify,
    snap_point,
)
from ..domain.ranking import Recommendation, RouteRisk, recommend, summarize_route
from ..domain.risk import UNKNOWN, RiskAssessment, RiskLevel, classify
from ..domain.sampling import Checkpoint, build_checkpoints
from ..providers.base import InvalidRequest, RoutePlan, RoutingProvider
from ..providers.open_meteo import clamp_range, forecast_request, parse_location
from .route_options import TARGET_ROUTES, generate_routes

logger = logging.getLogger(__name__)

# Each unique point is one call against the weather quota, so long trips read
# forecasts on a coarser grid. ETAs still vary per checkpoint.
FORECAST_SNAP_STEPS = (0.1, 0.2, 0.25, 0.5)
MAX_FORECAST_POINTS = 250
HOURS_OF_SERVICE_DRIVE_LIMIT_SECONDS = 11 * 3600
LOW_CONFIDENCE_LEAD_DAYS = 7
SLIDER_HOURS = 48
GEOMETRY_TOLERANCE_DEGREES = 0.0004  # about 40 m, invisible at trip zoom
PAST_DEPARTURE_GRACE = timedelta(minutes=5)
ROUTE_LABELS = ("Route A", "Route B", "Route C")
ROUTE_IDS = ("a", "b", "c")

RISK_NAMES = {
    RiskLevel.LOW: "low",
    RiskLevel.MODERATE: "moderate",
    RiskLevel.HIGH: "high",
    RiskLevel.SEVERE: "severe",
    RiskLevel.NO_TRAVEL: "no_travel",
}


class AnalysisExpired(Exception):
    pass


class ForecastMismatch(Exception):
    """The submitted forecasts do not line up with the points that were asked for."""


@dataclass(frozen=True)
class TripRequest:
    origin: LatLon
    destination: LatLon
    departure: datetime | None  # naive, origin-local. None means now.
    load_lb: float
    interval_miles: int


@dataclass(frozen=True)
class WeatherFailure:
    """Why the browser could not get forecasts."""

    rate_limited: bool
    reason: str = ""


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _rounded(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def forecast_window(departure_utc: datetime, routes: list[RoutePlan]) -> tuple[date, date]:
    """Days covering every ETA and the heatmap slider."""
    longest = max(route.travel_seconds for route in routes)
    span = timedelta(seconds=max(longest, SLIDER_HOURS * 3600))
    # One extra hour: rain at the last moment reads the following timestamp.
    return departure_utc.date(), (departure_utc + span + timedelta(hours=1)).date()


def load_record(analysis_id: str) -> dict:
    record = cache.get(f"analysis:{analysis_id}")
    if record is None:
        raise AnalysisExpired(analysis_id)
    return record


def parse_forecasts(points: list[LatLon], locations: list) -> dict[LatLon, HourlySeries]:
    """Pair submitted forecasts with their points. Bad ones read as missing."""
    if len(locations) != len(points):
        raise ForecastMismatch()
    parsed = ((point, parse_location(raw)) for point, raw in zip(points, locations))
    return {point: series for point, series in parsed if series is not None}


def plan_trip(trip: TripRequest, routing: RoutingProvider) -> dict:
    routes = generate_routes(
        routing, trip.origin, trip.destination, trip.departure,
        trip.load_lb + settings.TRUCK_TARE_LB,
    )
    departure = routes[0].departure
    departure_utc = departure.astimezone(timezone.utc)
    # TomTom accepts past times, and only its response knows the origin's zone.
    if trip.departure and departure_utc < datetime.now(timezone.utc) - PAST_DEPARTURE_GRACE:
        raise InvalidRequest("Departure time is in the past for the origin's time zone.")

    checkpoints = [
        build_checkpoints(
            route.points, route.length_miles, route.travel_seconds,
            trip.interval_miles, route.anchors,
        )
        for route in routes
    ]
    forecast_step = coarsest_needed_step(
        [(checkpoint.lat, checkpoint.lon) for items in checkpoints for checkpoint in items],
        FORECAST_SNAP_STEPS,
        MAX_FORECAST_POINTS,
    )
    window = clamp_range(
        *forecast_window(departure_utc, routes), datetime.now(timezone.utc).date()
    )
    if window is None:
        raise InvalidRequest("Departure is past the range of the forecast.")

    forecast_points = {
        (route_index, checkpoint.index): snap_point(
            (checkpoint.lat, checkpoint.lon), forecast_step
        )
        for route_index, items in enumerate(checkpoints)
        for checkpoint in items
    }
    points = list(dict.fromkeys(forecast_points.values()))
    corridor = build_corridor([
        simplify(route.points, GEOMETRY_TOLERANCE_DEGREES) for route in routes
    ])

    analysis_id = uuid.uuid4().hex
    cache.set(
        f"analysis:{analysis_id}",
        {
            "routes": routes,
            "checkpoints": checkpoints,
            "departure": departure,
            "load_lb": trip.load_lb,
            "interval_miles": trip.interval_miles,
            "forecast_step": forecast_step,
            "forecast_points": forecast_points,
            "points": points,
            "corridor": corridor,
        },
        settings.ANALYSIS_CACHE_SECONDS,
    )
    return {
        "analysis_id": analysis_id,
        "forecast": {
            **forecast_request(*window),
            "points": points,
            "cells": corridor.cells,
        },
    }


def _serialize_checkpoint(
    checkpoint: Checkpoint,
    departure_utc: datetime,
    sample: WeatherSample | None,
    risk: RiskAssessment,
) -> dict:
    return {
        "index": checkpoint.index,
        "miles": round(checkpoint.miles, 1),
        "lat": round(checkpoint.lat, 5),
        "lon": round(checkpoint.lon, 5),
        "eta": _iso(departure_utc + timedelta(seconds=checkpoint.eta_seconds)),
        "represented_miles": round(checkpoint.represented_miles, 2),
        "risk": RISK_NAMES[risk.level] if risk.level is not None else "unknown",
        "cause": risk.cause,
        "load_adjusted": risk.load_adjusted,
        "wind_mph": _rounded(sample.wind_mph, 1) if sample else None,
        "gust_mph": _rounded(sample.gust_mph, 1) if sample else None,
        "rain_in_hr": _rounded(sample.rain_in_hr, 3) if sample else None,
        "snow_in_hr": _rounded(sample.snow_in_hr, 3) if sample else None,
    }


def _serialize_summary(risk: RouteRisk) -> dict:
    return {
        "no_travel_miles": round(risk.no_travel_miles, 1),
        "severe_miles": round(risk.severe_miles, 1),
        "high_miles": round(risk.high_miles, 1),
        "moderate_miles": round(risk.miles_by_level[RiskLevel.MODERATE], 1),
        "low_miles": round(risk.miles_by_level[RiskLevel.LOW], 1),
        "unknown_miles": round(risk.unknown_miles, 1),
        "average_risk": _rounded(risk.average_risk, 2),
        "coverage": round(risk.coverage, 3),
    }


def _serialize_recommendation(result: Recommendation) -> dict:
    return {
        "status": result.status,
        "route_id": result.route_id,
        "least_bad_route_id": result.least_bad_route_id,
        "ranked_route_ids": result.ranked_route_ids,
        "deciding_factor": result.deciding_factor,
        "explanation": result.explanation,
        "warnings": result.warnings,
    }


def _notices(
    routes: list[RoutePlan],
    departure_utc: datetime,
    weather_failure: WeatherFailure | None,
    has_unknown_checkpoints: bool,
    forecast_step: float,
) -> list[dict]:
    notices = []

    def add(code: str, message: str) -> None:
        notices.append({"code": code, "message": message})

    if weather_failure and weather_failure.rate_limited:
        add("weather_unavailable", f"The free weather service is at its request limit, so risk is unknown. {weather_failure.reason}".strip())
    elif weather_failure:
        add("weather_unavailable", "The weather service did not respond, so risk is unknown. Try again shortly.")
    elif has_unknown_checkpoints:
        add("forecast_gaps", "Some checkpoints have no forecast and are shown as Unknown, so these routes may be riskier than they look.")
    if forecast_step > FORECAST_SNAP_STEPS[0]:
        add("coarse_forecast", f"On a trip this long, nearby checkpoints share a forecast, read about every {round(forecast_step * MILES_PER_DEGREE_LAT)} miles.")
    if len(routes) < TARGET_ROUTES:
        plural = "s" if len(routes) != 1 else ""
        add("fewer_routes", f"Only {len(routes)} distinct truck route{plural} found for this trip.")
    if max(route.travel_seconds for route in routes) > HOURS_OF_SERVICE_DRIVE_LIMIT_SECONDS:
        add("continuous_driving", "ETAs assume continuous driving with no rest stops. Real arrival times, and the weather met along the way, will differ on a trip this long.")
    if departure_utc - datetime.now(timezone.utc) > timedelta(days=LOW_CONFIDENCE_LEAD_DAYS):
        add("long_range_forecast", "This departure is over a week out. Forecasts at this range are much less reliable, so recheck closer to the day.")
    if any(route.has_non_truck_section for route in routes):
        add("non_truck_section", "Part of at least one route has no confirmed truck access. Check that stretch before relying on it.")
    if not all(route.anchors for route in routes):
        add("uniform_eta", "Detailed timing was unavailable for at least one route, so its ETAs assume constant speed.")
    return notices


def assess_trip(
    analysis_id: str, locations: list, weather_failure: WeatherFailure | None
) -> dict:
    record = load_record(analysis_id)
    routes: list[RoutePlan] = record["routes"]
    forecast_points = record["forecast_points"]
    load_lb = record["load_lb"]
    interval_miles = record["interval_miles"]
    departure = record["departure"]
    departure_utc = departure.astimezone(timezone.utc)

    if weather_failure:
        # Routes are still worth showing. Their risk is reported as Unknown.
        logger.warning("Browser weather lookup failed: %s", weather_failure)
        forecasts: dict[LatLon, HourlySeries] = {}
    else:
        forecasts = parse_forecasts(record["points"], locations)

    route_payloads = []
    summaries = []
    has_unknown = False
    for route_index, route in enumerate(routes):
        serialized = []
        segments = []
        for checkpoint in record["checkpoints"][route_index]:
            series = forecasts.get(forecast_points[route_index, checkpoint.index])
            moment = departure_utc.timestamp() + checkpoint.eta_seconds
            sample = sample_at(series, moment) if series else None
            risk = (
                classify(sample.wind_mph, sample.rain_in_hr, sample.snow_in_hr, load_lb)
                if sample
                else UNKNOWN
            )
            has_unknown = has_unknown or risk.level is None
            segments.append((checkpoint.represented_miles, risk.level))
            serialized.append(_serialize_checkpoint(checkpoint, departure_utc, sample, risk))

        summary = summarize_route(
            ROUTE_IDS[route_index], ROUTE_LABELS[route_index], route.travel_seconds, segments
        )
        summaries.append(summary)
        route_payloads.append({
            "id": summary.route_id,
            "label": summary.label,
            "length_miles": round(route.length_miles, 1),
            "travel_seconds": round(route.travel_seconds),
            "traffic_delay_seconds": round(route.traffic_delay_seconds),
            "arrival": _iso(departure_utc + timedelta(seconds=route.travel_seconds)),
            "geometry": [
                [round(lon, 5), round(lat, 5)]
                for lat, lon in simplify(route.points, GEOMETRY_TOLERANCE_DEGREES)
            ],
            "risk": _serialize_summary(summary),
            "checkpoints": serialized,
        })

    offset = departure.utcoffset()
    return {
        "analysis_id": analysis_id,
        "departure": _iso(departure_utc),
        "origin_utc_offset_minutes": round(offset.total_seconds() / 60) if offset else 0,
        "load_lb": load_lb,
        "interval_miles": interval_miles,
        "routes": route_payloads,
        "recommendation": _serialize_recommendation(recommend(summaries, interval_miles)),
        "notices": _notices(
            routes, departure_utc, weather_failure, has_unknown, record["forecast_step"]
        ),
    }
