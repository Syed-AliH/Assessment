"""Keyless stand-in for TomTom, for end-to-end runs without an API key.

Selected only by setting ROUTING_PROVIDER and GEOCODER, and lives under tests/
so that a deployed app can never use it. OSRM's public demo routes cars, so
results here prove the pipeline, not truck legality.
"""
from datetime import datetime, timezone, timedelta

import httpx

from trips.domain.geo import METERS_PER_MILE
from trips.domain.sampling import TimingAnchor
from trips.providers.base import NoRouteFound, Place, RoutePlan

URL = "https://router.project-osrm.org/route/v1/driving"
PLACES = [
    Place("Dallas, TX", 32.7767, -96.797),
    Place("Houston, TX", 29.7604, -95.3698),
    Place("Los Angeles, CA", 34.0522, -118.2437),
    Place("New York, NY", 40.7128, -74.006),
    Place("Denver, CO", 39.7392, -104.9903),
    Place("Chicago, IL", 41.8781, -87.6298),
    Place("Minneapolis, MN", 44.9778, -93.265),
    Place("Seattle, WA", 47.6062, -122.3321),
]
ORIGIN_OFFSET = timezone(timedelta(hours=-5))


def _plan(raw: dict, departure: datetime) -> RoutePlan:
    points = [(lat, lon) for lon, lat in raw["geometry"]["coordinates"]]
    anchors = []
    miles = seconds = 0.0
    for leg in raw["legs"]:
        for step in leg["steps"]:
            miles += step["distance"] / METERS_PER_MILE
            seconds += step["duration"]
            anchors.append(TimingAnchor(miles, seconds))
    return RoutePlan(
        points=points,
        length_miles=raw["distance"] / METERS_PER_MILE,
        travel_seconds=raw["duration"],
        departure=departure,
        anchors=anchors,
    )


class OsrmRouting:
    def routes(self, origin, destination, departure, gross_weight_lb, via=None):
        stops = [origin, *([via] if via else []), destination]
        path = ";".join(f"{lon:.5f},{lat:.5f}" for lat, lon in stops)
        response = httpx.get(
            f"{URL}/{path}",
            params={
                "overview": "full",
                "geometries": "geojson",
                "steps": "true",
                "alternatives": "false" if via else "3",
            },
            timeout=30,
        )
        data = response.json()
        if data.get("code") != "Ok":
            raise NoRouteFound(data.get("code", "no route"))
        start = (
            departure.replace(tzinfo=ORIGIN_OFFSET)
            if departure
            else datetime.now(ORIGIN_OFFSET).replace(microsecond=0)
        )
        return sorted(
            (_plan(route, start) for route in data["routes"]),
            key=lambda plan: plan.travel_seconds,
        )


class FixedGeocoder:
    def search(self, query):
        needle = query.lower()
        return [place for place in PLACES if needle in place.label.lower()]
