"""Weather risk classification. Thresholds and load rules come from the brief.

Band edges are continuous and never rounded. Where the brief's bands share a
value (rain 0.25 is both Moderate and High) the worse class wins, except at
the top: No Travel is strictly greater than, so 1.00 in/hr of rain is Severe.
"""
from dataclasses import dataclass
from enum import IntEnum

WIND_MODERATE_MPH = 25.0
WIND_HIGH_MPH = 35.0
WIND_SEVERE_MPH = 45.0
WIND_NO_TRAVEL_MPH = 55.0

HEAVY_LOAD_NO_TRAVEL_LB = 30_000
HEAVY_LOAD_SEVERE_LB = 40_000


class RiskLevel(IntEnum):
    """Ordered worst-last. Values double as the average-risk scale."""

    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4


@dataclass(frozen=True)
class RiskAssessment:
    """`level` is None when the forecast is missing: unknown, never Low."""

    level: RiskLevel | None
    cause: str | None = None
    load_adjusted: bool = False


UNKNOWN = RiskAssessment(level=None)


def wind_risk(wind_mph: float) -> RiskLevel:
    if wind_mph >= WIND_NO_TRAVEL_MPH:
        return RiskLevel.NO_TRAVEL
    if wind_mph >= WIND_SEVERE_MPH:
        return RiskLevel.SEVERE
    if wind_mph >= WIND_HIGH_MPH:
        return RiskLevel.HIGH
    if wind_mph >= WIND_MODERATE_MPH:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def rain_risk(rain_in_hr: float) -> RiskLevel:
    if rain_in_hr > 1.00:
        return RiskLevel.NO_TRAVEL
    if rain_in_hr >= 0.50:
        return RiskLevel.SEVERE
    if rain_in_hr >= 0.25:
        return RiskLevel.HIGH
    if rain_in_hr >= 0.10:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def snow_risk(snow_in_hr: float) -> RiskLevel:
    if snow_in_hr > 3.0:
        return RiskLevel.NO_TRAVEL
    if snow_in_hr >= 2.0:
        return RiskLevel.SEVERE
    if snow_in_hr >= 1.0:
        return RiskLevel.HIGH
    if snow_in_hr >= 0.5:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def apply_load_rules(wind_level: RiskLevel, load_lb: float) -> RiskLevel:
    """Escalate a wind level for heavy loads. Load never affects rain or snow."""
    if wind_level == RiskLevel.SEVERE and load_lb > HEAVY_LOAD_NO_TRAVEL_LB:
        return RiskLevel.NO_TRAVEL
    if wind_level == RiskLevel.HIGH and load_lb > HEAVY_LOAD_SEVERE_LB:
        return RiskLevel.SEVERE
    return wind_level


def classify(
    wind_mph: float | None,
    rain_in_hr: float | None,
    snow_in_hr: float | None,
    load_lb: float,
) -> RiskAssessment:
    """Worst of wind, rain and snow, after load rules.

    A partial forecast is Unknown: reporting Low from the fields that happen
    to be present could hide the one that is dangerous.
    """
    if wind_mph is None or rain_in_hr is None or snow_in_hr is None:
        return UNKNOWN

    base_wind = wind_risk(wind_mph)
    wind = apply_load_rules(base_wind, load_lb)
    # max() keeps the first of equals, so a tie is attributed to wind.
    level, cause = max(
        (wind, "wind"),
        (rain_risk(rain_in_hr), "rain"),
        (snow_risk(snow_in_hr), "snow"),
        key=lambda pair: pair[0],
    )
    if level == RiskLevel.LOW:
        return RiskAssessment(level=level)
    return RiskAssessment(
        level=level,
        cause=cause,
        load_adjusted=cause == "wind" and wind != base_wind,
    )
