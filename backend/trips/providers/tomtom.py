"""TomTom routing and geocoding."""
from datetime import datetime
from urllib.parse import quote

import httpx

from ..domain.geo import METERS_PER_MILE, LatLon, cumulative_miles
from ..domain.sampling import TimingAnchor
from .base import (
    NoRouteFound,
    Place,
    ProviderError,
    RateLimited,
    RoutePlan,
    UpstreamUnavailable,
)

BASE_URL = "https://api.tomtom.com"
KG_PER_LB = 0.45359237
MAX_ALTERNATIVES = 4
GEOCODE_COUNTRIES = "US,CA"
GEOCODE_LIMIT = 6
# TomTom marks the few metres from a pin to the nearest truck road as "other"
# on most routes, so only a stretch longer than this is worth a warning.
NON_TRUCK_MILES_THRESHOLD = 1.0


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code == 429:
        raise RateLimited("TomTom rate limit reached")
    if response.status_code in (401, 403):
        raise UpstreamUnavailable("TomTom rejected the API key")
    if response.status_code == 400:
        text = response.text.upper()
        if "NO_ROUTE" in text or "NO ROUTE" in text:
            raise NoRouteFound("No truck route between these points")
        raise UpstreamUnavailable(f"TomTom rejected the request: {response.text[:200]}")
    if response.status_code >= 400:
        raise UpstreamUnavailable(f"TomTom returned {response.status_code}")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _non_truck_miles(raw: dict, points: list[LatLon]) -> float:
    along = cumulative_miles(points)
    return sum(
        along[section["endPointIndex"]] - along[section["startPointIndex"]]
        for section in raw.get("sections", [])
        if section.get("travelMode") == "other"
    )


def parse_route(raw: dict) -> RoutePlan:
    summary = raw["summary"]
    points = [
        (point["latitude"], point["longitude"])
        for leg in raw["legs"]
        for point in leg["points"]
    ]
    if len(points) < 2:
        raise ProviderError("TomTom returned a route without geometry")
    instructions = raw.get("guidance", {}).get("instructions", [])
    anchors = [
        TimingAnchor(
            miles=step["routeOffsetInMeters"] / METERS_PER_MILE,
            seconds=step["travelTimeInSeconds"],
        )
        for step in instructions
        if "routeOffsetInMeters" in step and "travelTimeInSeconds" in step
    ]
    return RoutePlan(
        points=points,
        length_miles=summary["lengthInMeters"] / METERS_PER_MILE,
        travel_seconds=summary["travelTimeInSeconds"],
        departure=_parse_time(summary["departureTime"]),
        anchors=anchors,
        traffic_delay_seconds=summary.get("trafficDelayInSeconds", 0),
        has_non_truck_section=_non_truck_miles(raw, points) > NON_TRUCK_MILES_THRESHOLD,
    )


class TomTomClient:
    """Implements RoutingProvider and Geocoder."""

    def __init__(self, api_key: str, timeout: float = 25.0):
        if not api_key:
            raise UpstreamUnavailable("TOMTOM_API_KEY is not configured")
        self._key = api_key
        self._timeout = timeout

    def _get(self, path: str, params: dict) -> dict:
        try:
            response = httpx.get(
                f"{BASE_URL}{path}",
                params={**params, "key": self._key},
                timeout=self._timeout,
            )
        except httpx.HTTPError as error:
            # The exception text can include the URL, and the URL has the key.
            raise UpstreamUnavailable(f"Could not reach TomTom: {type(error).__name__}") from None
        _raise_for_status(response)
        try:
            return response.json()
        except ValueError:
            raise UpstreamUnavailable("TomTom returned an unreadable response") from None

    def routes(
        self,
        origin: LatLon,
        destination: LatLon,
        departure: datetime | None,
        gross_weight_lb: float,
        via: LatLon | None = None,
    ) -> list[RoutePlan]:
        stops = [origin, *([via] if via else []), destination]
        locations = ":".join(f"{lat:.6f},{lon:.6f}" for lat, lon in stops)
        params = {
            "travelMode": "truck",
            "vehicleCommercial": "true",
            "vehicleWeight": round(gross_weight_lb * KG_PER_LB),
            "routeType": "fastest",
            "traffic": "true",
            "departAt": departure.isoformat(timespec="seconds") if departure else "now",
            "instructionsType": "coded",
            "sectionType": "travelMode",
        }
        if not via:
            # Alternatives are only requested on the direct route.
            params["maxAlternatives"] = MAX_ALTERNATIVES
        data = self._get(f"/routing/1/calculateRoute/{quote(locations, safe=':,')}/json", params)
        try:
            routes = [parse_route(route) for route in data.get("routes", [])]
        except (KeyError, TypeError, ValueError) as error:
            raise UpstreamUnavailable(f"Unexpected TomTom route format: {error!r}") from None
        if not routes:
            raise NoRouteFound("No truck route between these points")
        return sorted(routes, key=lambda route: route.travel_seconds)

    def search(self, query: str) -> list[Place]:
        data = self._get(
            f"/search/2/geocode/{quote(query, safe='')}.json",
            {"countrySet": GEOCODE_COUNTRIES, "limit": GEOCODE_LIMIT, "typeahead": "true"},
        )
        # Results can repeat a label, and identical options are no use to a driver.
        places: dict[str, Place] = {}
        for result in data.get("results", []):
            try:
                label = result["address"]["freeformAddress"]
                place = Place(label, result["position"]["lat"], result["position"]["lon"])
            except (KeyError, TypeError):
                continue
            places.setdefault(label, place)
        return list(places.values())
