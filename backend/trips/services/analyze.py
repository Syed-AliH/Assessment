"""Run a trip end to end: routes, checkpoints, weather, risk, recommendation."""
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from django.conf import settings
from django.core.cache import cache

from ..domain.forecast_time import WeatherSample, sample_at
from ..domain.geo import LatLon, simplify, snap_point
from ..domain.ranking import Recommendation, RouteRisk, recommend, summarize_route
from ..domain.risk import UNKNOWN, RiskAssessment, RiskLevel, classify
from ..domain.sampling import Checkpoint, build_checkpoints
from ..providers.base import (
    InvalidRequest,
    ProviderError,
    RoutePlan,
    RoutingProvider,
    WeatherProvider,
)
from .route_options import TARGET_ROUTES, generate_routes
from .weather import cached_forecast

FORECAST_SNAP_DEGREES = 0.1
HOURS_OF_SERVICE_DRIVE_LIMIT_SECONDS = 11 * 3600
LOW_CONFIDENCE_LEAD_DAYS = 7
SLIDER_HOURS = 48
PAST_DEPARTURE_GRACE = timedelta(minutes=5)
GEOMETRY_TOLERANCE_DEGREES = 0.0004  # about 40 m, invisible at trip zoom
ROUTE_LABELS = ("Route A", "Route B", "Route C")
ROUTE_IDS = ("a", "b", "c")

RISK_NAMES = {
    RiskLevel.LOW: "low",
    RiskLevel.MODERATE: "moderate",
    RiskLevel.HIGH: "high",
    RiskLevel.SEVERE: "severe",
    RiskLevel.NO_TRAVEL: "no_travel",
}


@dataclass(frozen=True)
class TripRequest:
    origin: LatLon
    destination: LatLon
    departure: datetime | None  # naive, origin-local. None means now.
    load_lb: float
    interval_miles: int


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
    weather_failed: bool,
    has_unknown_checkpoints: bool,
) -> list[dict]:
    notices = []

    def add(code: str, message: str) -> None:
        notices.append({"code": code, "message": message})

    if weather_failed:
        add("weather_unavailable", "Weather data could not be loaded, so risk is unknown. Try again shortly.")
    elif has_unknown_checkpoints:
        add("forecast_gaps", "Some checkpoints have no forecast and are shown as Unknown, so these routes may be riskier than they look.")
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


def analyze_trip(
    trip: TripRequest, routing: RoutingProvider, weather: WeatherProvider
) -> dict:
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

    forecast_points = {
        (route_index, checkpoint.index): snap_point(
            (checkpoint.lat, checkpoint.lon), FORECAST_SNAP_DEGREES
        )
        for route_index, items in enumerate(checkpoints)
        for checkpoint in items
    }
    start, end = forecast_window(departure_utc, routes)
    weather_failed = False
    try:
        forecasts = cached_forecast(weather, list(forecast_points.values()), start, end)
    except ProviderError:
        # Routes are still worth showing. Their risk is reported as Unknown.
        forecasts, weather_failed = {}, True

    route_payloads = []
    summaries = []
    has_unknown = False
    for route_index, route in enumerate(routes):
        serialized = []
        segments = []
        for checkpoint in checkpoints[route_index]:
            series = forecasts.get(forecast_points[route_index, checkpoint.index])
            moment = departure_utc.timestamp() + checkpoint.eta_seconds
            sample = sample_at(series, moment) if series else None
            risk = (
                classify(sample.wind_mph, sample.rain_in_hr, sample.snow_in_hr, trip.load_lb)
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

    analysis_id = uuid.uuid4().hex
    cache.set(
        f"analysis:{analysis_id}",
        {
            "routes": [route.points for route in routes],
            "departure_utc": departure_utc,
            "load_lb": trip.load_lb,
            "window": (start, end),
        },
        settings.ANALYSIS_CACHE_SECONDS,
    )

    offset = departure.utcoffset()
    return {
        "analysis_id": analysis_id,
        "departure": _iso(departure_utc),
        "origin_utc_offset_minutes": round(offset.total_seconds() / 60) if offset else 0,
        "load_lb": trip.load_lb,
        "interval_miles": trip.interval_miles,
        "routes": route_payloads,
        "recommendation": _serialize_recommendation(recommend(summaries, trip.interval_miles)),
        "notices": _notices(routes, departure_utc, weather_failed, has_unknown),
    }
