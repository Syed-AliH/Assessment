import pytest

from trips.domain.ranking import (
    STATUS_INSUFFICIENT_DATA,
    STATUS_NO_SAFE_ROUTE,
    STATUS_RECOMMENDED,
    recommend,
    summarize_route,
)
from trips.domain.risk import RiskLevel as R

HOUR = 3600
INTERVAL = 25


def route(name, seconds=10 * HOUR, low=500, moderate=0, high=0, severe=0, no_travel=0, unknown=0):
    return summarize_route(
        name,
        f"Route {name}",
        seconds,
        [
            (low, R.LOW), (moderate, R.MODERATE), (high, R.HIGH),
            (severe, R.SEVERE), (no_travel, R.NO_TRAVEL), (unknown, None),
        ],
    )


def test_summary_is_mile_weighted_and_excludes_unknown():
    summary = route("A", low=75, severe=25, unknown=100)
    assert summary.average_risk == pytest.approx(0.75)
    assert summary.total_miles == 200
    assert summary.coverage == pytest.approx(0.5)


def test_all_unknown_has_no_average():
    assert route("A", low=0, unknown=100).average_risk is None


def test_severe_decides_first_even_against_more_high_and_longer_time():
    safe = route("A", seconds=20 * HOUR, severe=0, high=300)
    risky = route("B", seconds=5 * HOUR, severe=25, high=0)
    result = recommend([risky, safe], INTERVAL)
    assert result.route_id == "A"
    assert result.deciding_factor == "severe_miles"


def test_high_decides_when_severe_ties():
    result = recommend(
        [route("A", seconds=5 * HOUR, severe=50, high=100), route("B", seconds=9 * HOUR, severe=50, high=50)],
        INTERVAL,
    )
    assert result.route_id == "B"
    assert result.deciding_factor == "high_miles"


def test_average_decides_when_severe_and_high_tie():
    result = recommend(
        [route("A", seconds=5 * HOUR, moderate=300, low=200), route("B", seconds=9 * HOUR, moderate=100, low=400)],
        INTERVAL,
    )
    assert result.route_id == "B"
    assert result.deciding_factor == "average_risk"


def test_time_decides_when_risk_ties():
    result = recommend([route("A", seconds=9 * HOUR), route("B", seconds=8 * HOUR)], INTERVAL)
    assert result.route_id == "B"
    assert result.deciding_factor == "travel_time"


def test_no_travel_outranks_zero_severe():
    trap = route("A", no_travel=12.5, severe=0)
    honest = route("B", severe=200)
    result = recommend([trap, honest], INTERVAL)
    assert result.status == STATUS_RECOMMENDED
    assert result.route_id == "B"
    assert result.deciding_factor == "no_travel_miles"


def test_all_routes_no_travel_recommends_nothing():
    result = recommend([route("A", no_travel=100), route("B", no_travel=25)], INTERVAL)
    assert result.status == STATUS_NO_SAFE_ROUTE
    assert result.route_id is None
    assert result.least_bad_route_id == "B"
    assert "No safe route" in result.explanation


def test_sub_interval_mileage_difference_does_not_override_time():
    fast = route("A", seconds=8 * HOUR, severe=25.2)
    slow = route("B", seconds=10 * HOUR, severe=25.0)
    result = recommend([slow, fast], INTERVAL)
    assert result.route_id == "A"


def test_tiny_nonzero_severe_never_ties_with_zero():
    result = recommend([route("A", seconds=5 * HOUR, severe=5), route("B", seconds=9 * HOUR)], INTERVAL)
    assert result.route_id == "B"
    assert result.deciding_factor == "severe_miles"


def test_full_tie_says_so():
    result = recommend([route("A"), route("B")], INTERVAL)
    assert result.status == STATUS_RECOMMENDED
    assert result.deciding_factor == "tie"


def test_single_route():
    result = recommend([route("A")], INTERVAL)
    assert (result.route_id, result.deciding_factor) == ("A", "only_option")


def test_incomplete_coverage_warns():
    result = recommend([route("A", low=400, unknown=100)], INTERVAL)
    assert result.status == STATUS_RECOMMENDED
    assert "80%" in result.warnings[0]


def test_low_coverage_route_cannot_win_on_absence_of_data():
    blank = route("A", low=50, unknown=450)
    known = route("B", severe=100, low=400)
    result = recommend([blank, known], INTERVAL)
    assert result.route_id == "B"
    assert result.deciding_factor == "coverage"


def test_no_data_anywhere_is_insufficient():
    result = recommend([route("A", low=0, unknown=500), route("B", low=0, unknown=500)], INTERVAL)
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.route_id is None
    assert result.ranked_route_ids


def test_explanation_quotes_real_numbers():
    result = recommend([route("A", severe=100), route("B", severe=25)], INTERVAL)
    assert result.explanation == (
        "Route B is recommended: 25 Severe miles, against 100 on Route A."
    )


def test_rejects_empty():
    with pytest.raises(ValueError):
        recommend([], INTERVAL)
