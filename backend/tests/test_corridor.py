import pytest

from trips.domain.corridor import build_corridor
from trips.domain.geo import coarsest_needed_step, haversine_miles, snap_point

SHORT = [(32.78, -96.80), (29.76, -95.37)]  # Dallas to Houston
LONG = [(34.05, -118.24), (40.71, -74.00)]  # Los Angeles to New York


def test_short_trip_uses_finest_grid_within_budget():
    corridor = build_corridor([SHORT])
    assert corridor.step == 0.125
    assert 0 < len(corridor.cells) <= 300


def test_long_trip_coarsens_to_fit_budget():
    corridor = build_corridor([LONG])
    assert corridor.step == 0.5
    assert len(corridor.cells) <= 300


def test_three_spread_out_long_routes_stay_within_budget():
    routes = [LONG, [LONG[0], (30.0, -96.0), LONG[1]], [LONG[0], (45.0, -100.0), LONG[1]]]
    assert len(build_corridor(routes).cells) <= 300


def test_every_route_point_has_a_cell_nearby():
    corridor = build_corridor([SHORT])
    for fraction in (0, 0.25, 0.5, 0.75, 1):
        point = (
            SHORT[0][0] + (SHORT[1][0] - SHORT[0][0]) * fraction,
            SHORT[0][1] + (SHORT[1][1] - SHORT[0][1]) * fraction,
        )
        assert min(haversine_miles(point, cell) for cell in corridor.cells) < 10


def test_cells_stay_inside_the_corridor():
    corridor = build_corridor([SHORT], half_width_miles=30)
    origin, destination = SHORT
    for cell in corridor.cells:
        detour = haversine_miles(origin, cell) + haversine_miles(cell, destination)
        assert detour < haversine_miles(origin, destination) + 2 * 32


def test_overlapping_routes_do_not_duplicate_cells():
    single = build_corridor([SHORT])
    doubled = build_corridor([SHORT, SHORT])
    assert single.cells == doubled.cells
    assert len(set(single.cells)) == len(single.cells)


def test_grid_is_stable_for_nearby_trips():
    a = set(build_corridor([SHORT]).cells)
    shifted = [(lat + 0.01, lon) for lat, lon in SHORT]
    b = set(build_corridor([shifted]).cells)
    assert len(a & b) / len(a) > 0.9


def test_rejects_empty():
    with pytest.raises(ValueError):
        build_corridor([])


def test_step_coarsens_only_as_far_as_needed():
    points = [(30 + i * 0.1, -97.0) for i in range(100)]
    assert coarsest_needed_step(points, (0.1, 0.25, 0.5), 200) == 0.1
    assert coarsest_needed_step(points, (0.1, 0.25, 0.5), 45) == 0.25
    assert coarsest_needed_step(points, (0.1, 0.25, 0.5), 5) == 0.5


def test_snap_point_shares_keys_for_nearby_coordinates():
    assert snap_point((32.7812, -96.8011), 0.1) == snap_point((32.7999, -96.7600), 0.1)
    assert snap_point((32.7812, -96.8011), 0.1) == pytest.approx((32.8, -96.8))
