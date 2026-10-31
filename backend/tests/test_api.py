"""Whole request cycle through the API, with both vendors replaced by fakes."""
from datetime import datetime, timedelta, timezone

import pytest
from rest_framework.test import APIClient

from trips.domain.forecast_time import HourlySeries
from trips.domain.sampling import TimingAnchor
from trips.providers import registry
from trips.providers.base import (
    InvalidRequest,
    NoRouteFound,
    Place,
    RateLimited,
    RoutePlan,
    UpstreamUnavailable,
)
from trips.services import heatmap as heatmap_service

HOUR = 3600
DEPARTURE = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)

# Three corridors between the same ends: straight, east bulge, west bulge.
WEST_LON, MID_LON, EAST_LON = -97.0, -96.0, -95.0
ROUTES = {
    "fast": [(30.0, -96.0), (31.0, WEST_LON), (32.0, -96.0)],
    "mid": [(30.0, -96.0), (31.0, MID_LON), (32.0, -96.0)],
    "slow": [(30.0, -96.0), (31.0, EAST_LON), (32.0, -96.0)],
}


def plan(points, hours):
    return RoutePlan(
        points=points,
        length_miles=200,
        travel_seconds=hours * HOUR,
        departure=DEPARTURE.astimezone(timezone(timedelta(hours=-5))),
        anchors=[TimingAnchor(100, hours * HOUR / 2)],
    )


class FakeRouting:
    def __init__(self, plans=None, error=None):
        self.plans = plans or [plan(ROUTES["fast"], 3), plan(ROUTES["mid"], 4), plan(ROUTES["slow"], 5)]
        self.error = error
        self.calls = []

    def routes(self, origin, destination, departure, gross_weight_lb, via=None):
        self.calls.append({"departure": departure, "gross": gross_weight_lb, "via": via})
        if self.error:
            raise self.error
        return list(self.plans) if via is None else []


class FakeWeather:
    """Calm everywhere, except `storm_wind` mph west of `storm_east_of`."""

    def __init__(self, storm_wind=0.0, storm_west_of=None, missing=False, error=None):
        self.storm_wind = storm_wind
        self.storm_west_of = storm_west_of
        self.missing = missing
        self.error = error
        self.requested = []

    def forecast(self, points, start, end):
        self.requested.append(list(points))
        if self.error:
            raise self.error
        if self.missing:
            return {}
        first = int(DEPARTURE.timestamp()) - 24 * HOUR
        times = [first + i * HOUR for i in range(200)]
        result = {}
        for point in points:
            stormy = self.storm_west_of is not None and point[1] < self.storm_west_of
            wind = self.storm_wind if stormy else 5.0
            result[point] = HourlySeries(
                times=times,
                wind_mph=[wind] * 200,
                gust_mph=[wind * 1.3] * 200,
                rain_in=[0.0] * 200,
                snow_in=[0.0] * 200,
            )
        return result


@pytest.fixture
def api(monkeypatch, settings):
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK}

    def install(routing=None, weather=None):
        routing = routing or FakeRouting()
        weather = weather or FakeWeather()
        monkeypatch.setattr("trips.views.routing_provider", lambda: routing)
        monkeypatch.setattr("trips.views.weather_provider", lambda: weather)
        return routing, weather

    monkeypatch.setattr(
        "rest_framework.throttling.ScopedRateThrottle.allow_request", lambda *a: True
    )
    install.client = APIClient()
    return install


def body(**overrides):
    return {
        "origin": {"label": "Start", "lat": 30.0, "lon": -96.0},
        "destination": {"label": "End", "lat": 32.0, "lon": -96.0},
        "load_lb": 20_000,
        "interval_miles": 25,
        **overrides,
    }


def analyze(api, **overrides):
    return api.client.post("/api/trips/analyze", body(**overrides), format="json")


def test_happy_path_contract(api):
    api()
    response = analyze(api)
    assert response.status_code == 200
    data = response.json()
    assert [route["id"] for route in data["routes"]] == ["a", "b", "c"]
    assert data["origin_utc_offset_minutes"] == -300
    route = data["routes"][0]
    assert route["checkpoints"][0]["miles"] == 0
    assert route["checkpoints"][-1]["miles"] == 200
    assert route["risk"]["low_miles"] == 200
    assert route["geometry"][0] == [-96.0, 30.0]  # GeoJSON order
    assert data["recommendation"]["status"] == "recommended"
    assert data["recommendation"]["route_id"] == "a"
    assert data["recommendation"]["deciding_factor"] == "travel_time"


def test_eta_uses_timing_anchors_and_departure(api):
    api(routing=FakeRouting([plan(ROUTES["fast"], 4)]))
    data = analyze(api).json()
    checkpoint = next(c for c in data["routes"][0]["checkpoints"] if c["miles"] == 100)
    eta = datetime.fromisoformat(checkpoint["eta"].replace("Z", "+00:00"))
    assert eta - DEPARTURE == timedelta(hours=2)


def test_safer_slower_route_beats_faster_stormy_route(api):
    api(weather=FakeWeather(storm_wind=50, storm_west_of=-95.5))
    data = analyze(api).json()
    recommendation = data["recommendation"]
    assert recommendation["route_id"] == "c"
    assert recommendation["deciding_factor"] == "severe_miles"


def test_load_changes_the_recommendation_outcome(api):
    routing = FakeRouting([plan(ROUTES["fast"], 3)] * 1)
    api(routing=routing, weather=FakeWeather(storm_wind=50, storm_west_of=-95.0))
    light = analyze(api, load_lb=30_000).json()
    heavy = analyze(api, load_lb=30_001).json()
    assert light["routes"][0]["risk"]["no_travel_miles"] == 0
    assert heavy["routes"][0]["risk"]["no_travel_miles"] > 0
    assert heavy["recommendation"]["status"] == "no_safe_route"


def test_tare_is_added_for_routing_only(api, settings):
    settings.TRUCK_TARE_LB = 33_000
    routing, _ = api()
    analyze(api, load_lb=20_000)
    assert routing.calls[0]["gross"] == 53_000


def test_routes_share_forecasts_for_overlapping_points(api):
    _, weather = api()
    data = analyze(api).json()
    checkpoints = sum(len(route["checkpoints"]) for route in data["routes"])
    assert len(weather.requested[0]) < checkpoints


def test_weather_failure_shows_routes_as_unknown_not_low(api):
    api(weather=FakeWeather(error=UpstreamUnavailable("down")))
    response = analyze(api)
    assert response.status_code == 200
    data = response.json()
    assert data["recommendation"]["status"] == "insufficient_data"
    assert {c["risk"] for c in data["routes"][0]["checkpoints"]} == {"unknown"}
    assert "weather_unavailable" in [notice["code"] for notice in data["notices"]]


def test_weather_rate_limit_says_so(api):
    api(weather=FakeWeather(error=RateLimited("limit")))
    notice = next(n for n in analyze(api).json()["notices"] if n["code"] == "weather_unavailable")
    assert "request limit" in notice["message"]


def test_missing_forecasts_are_unknown(api):
    api(weather=FakeWeather(missing=True))
    data = analyze(api).json()
    assert data["routes"][0]["risk"]["coverage"] == 0
    assert data["routes"][0]["risk"]["average_risk"] is None


def test_fewer_than_three_routes_is_stated(api):
    api(routing=FakeRouting([plan(ROUTES["fast"], 3)]))
    data = analyze(api).json()
    assert len(data["routes"]) == 1
    assert "fewer_routes" in [notice["code"] for notice in data["notices"]]


def test_near_duplicate_routes_are_not_padded(api):
    api(routing=FakeRouting([plan(ROUTES["fast"], 3), plan(ROUTES["fast"], 3.1)]))
    assert len(analyze(api).json()["routes"]) == 1


def test_via_fallback_fills_missing_routes(api):
    class ViaRouting(FakeRouting):
        def routes(self, origin, destination, departure, gross_weight_lb, via=None):
            self.calls.append({"via": via})
            return [plan(ROUTES["slow" if via[1] > -96 else "mid"], 5)] if via else [self.plans[0]]

    routing = ViaRouting()
    api(routing=routing)
    data = analyze(api).json()
    assert len(data["routes"]) == 3
    assert sum(1 for call in routing.calls if call["via"]) == 2


def test_long_trip_notice(api):
    api(routing=FakeRouting([plan(ROUTES["fast"], 12)]))
    codes = [notice["code"] for notice in analyze(api).json()["notices"]]
    assert "continuous_driving" in codes


@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"load_lb": -1}, "load_lb"),
        ({"load_lb": 80_001}, "load_lb"),
        ({"interval_miles": 15}, "interval_miles"),
        ({"departure": "not-a-date"}, "departure"),
        ({"departure": "2020-01-01T08:00:00"}, "departure"),
        ({"departure": "2099-01-01T08:00:00"}, "departure"),
        ({"departure": "2026-11-05T08:00:00-05:00"}, "departure"),
        ({"destination": {"lat": 30.0, "lon": -96.0}}, "destination"),
        ({"origin": {"lat": 200, "lon": 0}}, "origin"),
    ],
)
def test_validation_errors_name_the_field(api, overrides, field):
    api()
    response = analyze(api, **overrides)
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert field in error["fields"]


def test_load_boundaries_are_accepted(api):
    api()
    assert analyze(api, load_lb=0).status_code == 200
    assert analyze(api, load_lb=80_000).status_code == 200


def test_naive_departure_reaches_the_router(api):
    routing, _ = api()
    moment = (datetime.utcnow() + timedelta(days=2)).replace(microsecond=0)
    analyze(api, departure=moment.isoformat())
    assert routing.calls[0]["departure"] == moment


def test_departure_past_in_the_origin_zone_is_rejected(api):
    past = plan(ROUTES["fast"], 3)
    past = RoutePlan(**{**past.__dict__, "departure": DEPARTURE - timedelta(hours=9)})
    api(routing=FakeRouting([past]))
    moment = (datetime.utcnow() - timedelta(hours=9)).replace(microsecond=0)
    response = analyze(api, departure=moment.isoformat())
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "error, status, code",
    [
        (NoRouteFound("x"), 422, "no_route"),
        (RateLimited("x"), 429, "rate_limited"),
        (UpstreamUnavailable("key secret"), 503, "upstream_unavailable"),
        (InvalidRequest("Departure time is in the past"), 400, "validation_error"),
    ],
)
def test_routing_errors_are_typed(api, error, status, code):
    api(routing=FakeRouting(error=error))
    response = analyze(api)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "secret" not in response.content.decode()


def test_heatmap_contract(api):
    api()
    analysis_id = analyze(api).json()["analysis_id"]
    response = api.client.get(f"/api/trips/{analysis_id}/heatmap")
    assert response.status_code == 200
    data = response.json()
    assert len(data["cells"]) == len(data["levels"]) > 0
    assert all(len(codes) == 49 for codes in data["levels"])
    assert set("".join(data["levels"])) == {"0"}


def test_heatmap_applies_load_rules(api):
    api(weather=FakeWeather(storm_wind=50, storm_west_of=0))
    light = analyze(api, load_lb=30_000).json()["analysis_id"]
    heavy = analyze(api, load_lb=30_001).json()["analysis_id"]
    assert set("".join(api.client.get(f"/api/trips/{light}/heatmap").json()["levels"])) == {"3"}
    assert set("".join(api.client.get(f"/api/trips/{heavy}/heatmap").json()["levels"])) == {"4"}


def test_heatmap_missing_forecast_is_unknown(api):
    api()
    analysis_id = analyze(api).json()["analysis_id"]
    api(weather=FakeWeather(missing=True))
    from django.core.cache import cache

    for key in list(cache._cache):
        if "wx:" in key:
            del cache._cache[key]
    levels = api.client.get(f"/api/trips/{analysis_id}/heatmap").json()["levels"]
    assert set("".join(levels)) == {"5"}


def test_heatmap_failure_is_an_error_not_a_blank_map(api):
    api()
    analysis_id = analyze(api).json()["analysis_id"]
    api(weather=FakeWeather(error=RateLimited("x")))
    from django.core.cache import cache

    for key in list(cache._cache):
        if "wx:" in key:
            del cache._cache[key]
    response = api.client.get(f"/api/trips/{analysis_id}/heatmap")
    assert response.status_code == 429


def test_expired_analysis(api):
    api()
    response = api.client.get("/api/trips/doesnotexist/heatmap")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "analysis_expired"


def test_geocode(api, monkeypatch):
    class FakeGeocoder:
        def search(self, query):
            return [Place("Dallas, TX", 32.8, -96.8)]

    monkeypatch.setattr("trips.views.geocoder", FakeGeocoder)
    assert api.client.get("/api/geocode?q=da").json() == {"results": []}
    results = api.client.get("/api/geocode?q=dallas").json()["results"]
    assert results == [{"label": "Dallas, TX", "lat": 32.8, "lon": -96.8}]


def test_hourly_codes_length_constant():
    assert len(heatmap_service.hourly_codes(None, 0, 0)) == 49


def test_app_page_is_revalidated_so_new_builds_appear(settings, tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html>")
    settings.FRONTEND_DIST = tmp_path
    response = APIClient().get("/")
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-cache"
