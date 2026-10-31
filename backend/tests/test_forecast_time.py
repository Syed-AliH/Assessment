import pytest

from trips.domain.forecast_time import HourlySeries, sample_at

H = 3600
T0 = 1_800_000_000 - 1_800_000_000 % H


def series(wind=(10, 20, 30), gust=(15, 25, 35), rain=(0.0, 0.2, 0.4), snow=(0.0, 1.0, 2.0)):
    return HourlySeries(
        times=[T0 + i * H for i in range(len(wind))],
        wind_mph=list(wind),
        gust_mph=list(gust),
        rain_in=list(rain),
        snow_in=list(snow),
    )


def test_precip_between_hours_uses_the_hour_ending_after_it():
    sample = sample_at(series(), T0 + H + 20 * 60)  # 14:20 reads the 15:00 stamp
    assert sample.rain_in_hr == 0.4
    assert sample.snow_in_hr == 2.0
    assert sample.gust_mph == 35


def test_wind_between_hours_is_interpolated():
    sample = sample_at(series(), T0 + H + 30 * 60)
    assert sample.wind_mph == pytest.approx(25)


def test_exact_hour_reads_that_stamp():
    sample = sample_at(series(), T0 + H)
    assert (sample.wind_mph, sample.rain_in_hr) == (20, 0.2)


@pytest.mark.parametrize("moment", [T0 - 1, T0 + 2 * H + 1])
def test_outside_series_is_none(moment):
    assert sample_at(series(), moment) is None


def test_first_and_last_stamps_are_inside():
    assert sample_at(series(), T0).wind_mph == 10
    assert sample_at(series(), T0 + 2 * H).wind_mph == 30


def test_empty_series():
    assert sample_at(HourlySeries([], [], [], [], []), T0) is None


def test_null_wind_neighbour_gives_none_instead_of_guessing():
    sample = sample_at(series(wind=(10, None, 30)), T0 + 30 * 60)
    assert sample.wind_mph is None


def test_null_precip_stays_null():
    assert sample_at(series(rain=(0.0, None, 0.4)), T0 + 30 * 60).rain_in_hr is None
