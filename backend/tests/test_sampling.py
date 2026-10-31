import pytest

from trips.domain.sampling import TimingAnchor, build_checkpoints, checkpoint_miles

# Roughly 69 miles along a meridian.
LINE = [(30.0, -97.0), (31.0, -97.0)]


def test_positions_include_origin_and_destination():
    assert checkpoint_miles(60, 25) == [0, 25, 50, 60]


def test_exact_multiple_does_not_duplicate_destination():
    assert checkpoint_miles(50, 25) == [0, 25, 50]


def test_route_shorter_than_interval_keeps_both_ends():
    assert checkpoint_miles(8, 50) == [0, 8]


@pytest.mark.parametrize("bad", [(0, 25), (-1, 25), (10, 0)])
def test_rejects_invalid_lengths(bad):
    with pytest.raises(ValueError):
        checkpoint_miles(*bad)


@pytest.mark.parametrize("total, interval", [(100, 25), (103.7, 25), (68, 10), (8, 50), (51, 50)])
def test_represented_miles_sum_to_route_length(total, interval):
    checkpoints = build_checkpoints(LINE, total, 3600, interval)
    assert sum(c.represented_miles for c in checkpoints) == pytest.approx(total)
    assert all(c.represented_miles > 0 for c in checkpoints)


def test_interior_checkpoint_owns_one_interval_and_ends_own_half():
    checkpoints = build_checkpoints(LINE, 100, 3600, 25)
    assert [c.represented_miles for c in checkpoints] == [12.5, 25, 25, 25, 12.5]


def test_coordinates_follow_geometry_and_scale_to_provider_length():
    checkpoints = build_checkpoints(LINE, 100, 3600, 50)
    assert checkpoints[0].lat == pytest.approx(30.0)
    assert checkpoints[1].lat == pytest.approx(30.5)
    assert checkpoints[-1].lat == pytest.approx(31.0)


def test_eta_without_anchors_is_uniform():
    checkpoints = build_checkpoints(LINE, 100, 4000, 25)
    assert [c.eta_seconds for c in checkpoints] == pytest.approx([0, 1000, 2000, 3000, 4000])


def test_anchors_capture_mixed_speed():
    # Slow first 10 miles (city, 30 min), then fast highway for the last 90.
    anchors = [TimingAnchor(10, 1800)]
    checkpoints = build_checkpoints(LINE, 100, 7200, 50, anchors)
    uniform = build_checkpoints(LINE, 100, 7200, 50)
    assert checkpoints[1].eta_seconds == pytest.approx(1800 + 5400 * 40 / 90)
    assert checkpoints[1].eta_seconds != pytest.approx(uniform[1].eta_seconds)


def test_eta_is_monotonic_with_noisy_anchors():
    anchors = [TimingAnchor(30, 2000), TimingAnchor(60, 1500), TimingAnchor(60, 1700), TimingAnchor(90, 99999)]
    checkpoints = build_checkpoints(LINE, 100, 7200, 10, anchors)
    etas = [c.eta_seconds for c in checkpoints]
    assert etas == sorted(etas)
    assert etas[0] == 0
    assert etas[-1] == 7200


def test_rejects_degenerate_geometry():
    with pytest.raises(ValueError):
        build_checkpoints([(30.0, -97.0)], 10, 100, 5)
    with pytest.raises(ValueError):
        build_checkpoints([(30.0, -97.0), (30.0, -97.0)], 10, 100, 5)
