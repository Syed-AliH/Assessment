import pytest

from trips.domain.risk import RiskLevel as R
from trips.domain.risk import classify, rain_risk, snow_risk, wind_risk


@pytest.mark.parametrize(
    "mph, expected",
    [
        (0, R.LOW), (24.99, R.LOW),
        (25, R.MODERATE), (34.99, R.MODERATE),
        (35, R.HIGH), (34.5, R.MODERATE), (44.99, R.HIGH),
        (45, R.SEVERE), (54.99, R.SEVERE),
        (55, R.NO_TRAVEL), (90, R.NO_TRAVEL),
    ],
)
def test_wind_bands(mph, expected):
    assert wind_risk(mph) == expected


@pytest.mark.parametrize(
    "inches, expected",
    [
        (0, R.LOW), (0.099, R.LOW),
        (0.10, R.MODERATE), (0.249, R.MODERATE),
        (0.25, R.HIGH), (0.499, R.HIGH),
        (0.50, R.SEVERE), (1.00, R.SEVERE),
        (1.0001, R.NO_TRAVEL),
    ],
)
def test_rain_bands_and_shared_edges(inches, expected):
    assert rain_risk(inches) == expected


@pytest.mark.parametrize(
    "inches, expected",
    [
        (0, R.LOW), (0.49, R.LOW),
        (0.5, R.MODERATE), (0.99, R.MODERATE),
        (1.0, R.HIGH), (1.99, R.HIGH),
        (2.0, R.SEVERE), (3.0, R.SEVERE),
        (3.01, R.NO_TRAVEL),
    ],
)
def test_snow_bands_and_shared_edges(inches, expected):
    assert snow_risk(inches) == expected


@pytest.mark.parametrize(
    "wind, load, expected, adjusted",
    [
        # >=55 is No Travel at any load, including empty.
        (55, 0, R.NO_TRAVEL, False),
        # 45-54: >30,000 strict.
        (45, 30_000, R.SEVERE, False),
        (45, 30_001, R.NO_TRAVEL, True),
        (54.99, 30_000, R.SEVERE, False),
        (54.99, 30_001, R.NO_TRAVEL, True),
        # 35-44: >40,000 strict.
        (35, 40_000, R.HIGH, False),
        (35, 40_001, R.SEVERE, True),
        (44.99, 40_001, R.SEVERE, True),
        # Heavy load alone changes nothing below 35 mph.
        (34.99, 80_000, R.MODERATE, False),
        (0, 80_000, R.LOW, False),
    ],
)
def test_load_rules(wind, load, expected, adjusted):
    result = classify(wind, 0, 0, load)
    assert result.level == expected
    assert result.load_adjusted is adjusted


def test_load_does_not_escalate_rain_or_snow():
    assert classify(0, 0.6, 0, 80_000).level == R.SEVERE
    assert classify(0, 0, 2.5, 80_000).level == R.SEVERE


def test_worst_condition_wins_and_is_named():
    result = classify(26, 0.6, 1.2, 10_000)
    assert (result.level, result.cause) == (R.SEVERE, "rain")
    result = classify(26, 0.1, 2.5, 10_000)
    assert (result.level, result.cause) == (R.SEVERE, "snow")


def test_load_escalated_wind_can_outrank_rain():
    result = classify(40, 0.3, 0, 45_000)
    assert (result.level, result.cause, result.load_adjusted) == (R.SEVERE, "wind", True)


def test_load_adjustment_not_claimed_when_another_factor_controls():
    result = classify(40, 2.0, 0, 45_000)
    assert (result.level, result.cause, result.load_adjusted) == (R.NO_TRAVEL, "rain", False)


def test_low_has_no_cause():
    assert classify(5, 0, 0, 10_000).cause is None


@pytest.mark.parametrize("args", [(None, 0, 0), (0, None, 0), (0, 0, None), (None, None, None)])
def test_any_missing_field_is_unknown_not_low(args):
    assert classify(*args, 10_000).level is None
