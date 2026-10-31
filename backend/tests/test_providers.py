import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from trips.providers.base import (
    NoRouteFound,
    RateLimited,
    UpstreamUnavailable,
)
from trips.providers.open_meteo import clamp_range, parse_location
from trips.providers.tomtom import BASE_URL, TomTomClient, parse_route


def hourly(**overrides):
    base = {
        "time": [1000, 4600],
        "wind_speed_10m": [10.0, 20.0],
        "wind_gusts_10m": [15.0, 25.0],
        "rain": [2.54, 0.0],
        "showers": [2.54, 0.0],
        "snowfall": [2.54, 0.0],
    }
    return {"hourly": {**base, **overrides}}


def test_units_convert_to_inches_and_rain_includes_showers():
    series = parse_location(hourly())
    assert series.rain_in[0] == pytest.approx(0.2)
    assert series.snow_in[0] == pytest.approx(1.0)
    assert series.wind_mph == [10.0, 20.0]


def test_null_values_stay_null():
    series = parse_location(hourly(showers=[None, 0.0], snowfall=[None, 0.0]))
    assert series.rain_in[0] is None
    assert series.snow_in[0] is None


@pytest.mark.parametrize(
    "raw",
    [{}, {"hourly": None}, hourly(time=[]), hourly(rain=[1.0]), {"hourly": {"time": [1]}}],
)
def test_malformed_location_is_rejected(raw):
    assert parse_location(raw) is None


def test_range_is_trimmed_to_forecast_window():
    today = date(2026, 1, 1)
    assert clamp_range(date(2025, 12, 30), date(2026, 1, 2), today) == (today, date(2026, 1, 2))
    assert clamp_range(today, date(2026, 3, 1), today) == (today, date(2026, 1, 16))
    assert clamp_range(date(2026, 2, 1), date(2026, 2, 3), today) is None


@pytest.mark.parametrize(
    "bad",
    [
        hourly(time=["soon", "later"]),
        hourly(time=[4600, 1000]),
        hourly(wind_speed_10m=["high", 20.0]),
        hourly(rain=[True, 0.0]),
    ],
)
def test_nonsense_submissions_are_rejected(bad):
    assert parse_location(bad) is None


RAW_ROUTE = {
    "summary": {
        "lengthInMeters": 16093.44,
        "travelTimeInSeconds": 1200,
        "trafficDelayInSeconds": 60,
        "departureTime": "2026-11-01T08:00:00-05:00",
    },
    "legs": [
        {"points": [{"latitude": 30.0, "longitude": -97.0}, {"latitude": 30.1, "longitude": -97.0}]},
        {"points": [{"latitude": 30.2, "longitude": -97.0}]},
    ],
    "guidance": {
        "instructions": [
            {"routeOffsetInMeters": 8046.72, "travelTimeInSeconds": 900},
            {"routeOffsetInMeters": 1},
        ]
    },
    "sections": [{"sectionType": "TRAVEL_MODE", "travelMode": "other", "startPointIndex": 0, "endPointIndex": 2}],
}


def test_parse_route_joins_legs_and_reads_timing():
    plan = parse_route(RAW_ROUTE)
    assert len(plan.points) == 3
    assert plan.length_miles == pytest.approx(10)
    assert plan.anchors[0].miles == pytest.approx(5)
    assert len(plan.anchors) == 1
    assert plan.has_non_truck_section
    assert plan.departure.utcoffset() == timedelta(hours=-5)


def test_short_non_truck_stretch_at_the_pin_is_ignored():
    raw = {**RAW_ROUTE, "sections": [
        {"sectionType": "TRAVEL_MODE", "travelMode": "other", "startPointIndex": 0, "endPointIndex": 0},
        {"sectionType": "TRAVEL_MODE", "travelMode": "truck", "startPointIndex": 0, "endPointIndex": 2},
    ]}
    assert not parse_route(raw).has_non_truck_section


def test_recorded_tomtom_response_parses():
    data = json.loads((Path(__file__).parent / "fixtures" / "tomtom_route.json").read_text())
    plans = [parse_route(route) for route in data["routes"]]
    assert plans
    for plan in plans:
        assert plan.departure.utcoffset() is not None
        assert not plan.has_non_truck_section
        assert plan.length_miles > 20
        seconds = [anchor.seconds for anchor in plan.anchors]
        miles = [anchor.miles for anchor in plan.anchors]
        assert len(miles) > 2
        assert seconds == sorted(seconds) and miles == sorted(miles)
        assert miles[-1] == pytest.approx(plan.length_miles, abs=0.1)
        assert seconds[-1] == pytest.approx(plan.travel_seconds, abs=60)


@respx.mock
def test_routes_request_carries_truck_parameters_in_kg():
    route = respx.get(url__startswith=f"{BASE_URL}/routing/").mock(
        return_value=httpx.Response(200, json={"routes": [RAW_ROUTE]})
    )
    TomTomClient("k").routes((30, -97), (31, -97), None, 73_000)
    params = route.calls[0].request.url.params
    assert params["travelMode"] == "truck"
    assert params["vehicleWeight"] == "33112"
    assert params["departAt"] == "now"
    assert params["maxAlternatives"] == "4"


@respx.mock
def test_via_request_has_three_stops_and_no_alternatives():
    route = respx.get(url__startswith=f"{BASE_URL}/routing/").mock(
        return_value=httpx.Response(200, json={"routes": [RAW_ROUTE]})
    )
    TomTomClient("k").routes((30, -97), (31, -97), None, 73_000, via=(30.5, -98))
    assert ":30.500000,-98.000000:" in str(route.calls[0].request.url)
    assert "maxAlternatives" not in route.calls[0].request.url.params


@respx.mock
@pytest.mark.parametrize(
    "status, body, expected",
    [
        (400, '{"detailedError":{"code":"NO_ROUTE_FOUND"}}', NoRouteFound),
        (400, "something else", UpstreamUnavailable),
        (401, "unauthorized", UpstreamUnavailable),
        (403, "forbidden", UpstreamUnavailable),
        (429, "slow down", RateLimited),
        (503, "down", UpstreamUnavailable),
        (200, "<html>not json</html>", UpstreamUnavailable),
        (200, '{"routes":[]}', NoRouteFound),
        (200, '{"routes":[{"summary":{}}]}', UpstreamUnavailable),
    ],
)
def test_routing_failures_are_typed(status, body, expected):
    respx.get(url__startswith=f"{BASE_URL}/routing/").mock(
        return_value=httpx.Response(status, text=body)
    )
    with pytest.raises(expected):
        TomTomClient("k").routes((30, -97), (31, -97), None, 73_000)


@respx.mock
def test_connection_error_does_not_leak_the_key():
    respx.get(url__startswith=f"{BASE_URL}/routing/").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(UpstreamUnavailable) as caught:
        TomTomClient("secret-key").routes((30, -97), (31, -97), None, 73_000)
    assert "secret-key" not in str(caught.value)


def test_missing_key_is_a_clear_error():
    with pytest.raises(UpstreamUnavailable):
        TomTomClient("")


@respx.mock
def test_geocode_skips_incomplete_results():
    respx.get(url__startswith=f"{BASE_URL}/search/").mock(
        return_value=httpx.Response(200, json={"results": [
            {"address": {"freeformAddress": "Dallas, TX"}, "position": {"lat": 32.8, "lon": -96.8}},
            {"address": {"freeformAddress": "Dallas, TX"}, "position": {"lat": 32.9, "lon": -96.9}},
            {"address": {}},
        ]})
    )
    places = TomTomClient("k").search("Dallas")
    assert [(place.label, place.lat) for place in places] == [("Dallas, TX", 32.8)]
