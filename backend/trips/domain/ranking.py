"""Pick the best route and explain why.

Order from the brief: fewest Severe miles, fewest High miles, lowest average
risk, shortest travel time. The brief does not rank No Travel, so it goes
first: a route that crosses No Travel weather is never recommended, however
few Severe miles it has.

Mileages are compared in whole sampling intervals. Sampling cannot measure
finer than that, and a 0.2-mile gap should not outvote a shorter trip. Any
non-zero mileage counts as at least one interval so that it never ties zero.
"""
import math
from collections.abc import Iterable
from dataclasses import dataclass, field

from .risk import RiskLevel

# Below this much forecast coverage a clean-looking score is mostly absence of
# data, so the route cannot be recommended.
MIN_COVERAGE = 0.5

STATUS_RECOMMENDED = "recommended"
STATUS_NO_SAFE_ROUTE = "no_safe_route"
STATUS_INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True)
class RouteRisk:
    route_id: str
    label: str
    travel_seconds: float
    total_miles: float
    miles_by_level: dict[RiskLevel, float]
    unknown_miles: float
    average_risk: float | None

    @property
    def no_travel_miles(self) -> float:
        return self.miles_by_level[RiskLevel.NO_TRAVEL]

    @property
    def severe_miles(self) -> float:
        return self.miles_by_level[RiskLevel.SEVERE]

    @property
    def high_miles(self) -> float:
        return self.miles_by_level[RiskLevel.HIGH]

    @property
    def coverage(self) -> float:
        if self.total_miles <= 0:
            return 0.0
        return max(0.0, 1 - self.unknown_miles / self.total_miles)


@dataclass(frozen=True)
class Recommendation:
    status: str
    route_id: str | None
    least_bad_route_id: str | None
    ranked_route_ids: list[str]
    deciding_factor: str | None
    explanation: str
    warnings: list[str] = field(default_factory=list)


def summarize_route(
    route_id: str,
    label: str,
    travel_seconds: float,
    segments: Iterable[tuple[float, RiskLevel | None]],
) -> RouteRisk:
    """Roll (miles, level) pairs up. Unknown miles stay out of the average."""
    miles_by_level = {level: 0.0 for level in RiskLevel}
    unknown = 0.0
    weighted = 0.0
    for miles, level in segments:
        if level is None:
            unknown += miles
        else:
            miles_by_level[level] += miles
            weighted += miles * int(level)
    known = sum(miles_by_level.values())
    return RouteRisk(
        route_id=route_id,
        label=label,
        travel_seconds=travel_seconds,
        total_miles=known + unknown,
        miles_by_level=miles_by_level,
        unknown_miles=unknown,
        average_risk=weighted / known if known > 0 else None,
    )


def _intervals(miles: float, interval_miles: float) -> int:
    if miles <= 0:
        return 0
    return max(1, math.floor(miles / interval_miles + 0.5))


def _sort_key(route: RouteRisk, interval_miles: float) -> tuple:
    average = route.average_risk if route.average_risk is not None else math.inf
    return (
        route.coverage < MIN_COVERAGE,
        _intervals(route.no_travel_miles, interval_miles),
        _intervals(route.severe_miles, interval_miles),
        _intervals(route.high_miles, interval_miles),
        round(average, 2),
        round(route.travel_seconds),
    )


def _duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if hours else f"{minutes} min"


def _describe_gap(best: RouteRisk, other: RouteRisk, position: int) -> tuple[str, str]:
    """Name the first criterion separating two routes. Position indexes the sort key."""
    if position == 0:
        return "coverage", (
            f"it has forecast data for {best.coverage:.0%} of the trip, "
            f"against {other.coverage:.0%} for {other.label}"
        )
    if position == 1:
        return "no_travel_miles", (
            f"{best.no_travel_miles:.0f} No Travel miles, "
            f"against {other.no_travel_miles:.0f} on {other.label}"
        )
    if position == 2:
        return "severe_miles", (
            f"{best.severe_miles:.0f} Severe miles, "
            f"against {other.severe_miles:.0f} on {other.label}"
        )
    if position == 3:
        return "high_miles", (
            f"Severe miles are level with {other.label}, and it has "
            f"{best.high_miles:.0f} High miles against {other.high_miles:.0f}"
        )
    if position == 4:
        return "average_risk", (
            f"Severe and High miles are level with {other.label}, and its average "
            f"risk is lower ({best.average_risk:.2f} against {other.average_risk:.2f})"
        )
    return "travel_time", (
        f"weather risk is level with {other.label}, and it is faster "
        f"({_duration(best.travel_seconds)} against {_duration(other.travel_seconds)})"
    )


def _deciding_gap(
    best: RouteRisk, runner_up: RouteRisk, interval_miles: float
) -> tuple[str, str] | None:
    best_key = _sort_key(best, interval_miles)
    other_key = _sort_key(runner_up, interval_miles)
    for position, (a, b) in enumerate(zip(best_key, other_key)):
        if a != b:
            return _describe_gap(best, runner_up, position)
    return None


def recommend(routes: list[RouteRisk], interval_miles: float) -> Recommendation:
    if not routes:
        raise ValueError("no routes to rank")

    ranked = sorted(routes, key=lambda route: _sort_key(route, interval_miles))
    ranked_ids = [route.route_id for route in ranked]
    best = ranked[0]

    if best.coverage < MIN_COVERAGE:
        return Recommendation(
            status=STATUS_INSUFFICIENT_DATA,
            route_id=None,
            least_bad_route_id=None,
            ranked_route_ids=ranked_ids,
            deciding_factor=None,
            explanation=(
                "There is not enough forecast data along these routes to recommend one."
            ),
        )

    gap = _deciding_gap(best, ranked[1], interval_miles) if len(ranked) > 1 else None

    if best.no_travel_miles > 0:
        return Recommendation(
            status=STATUS_NO_SAFE_ROUTE,
            route_id=None,
            least_bad_route_id=best.route_id,
            ranked_route_ids=ranked_ids,
            deciding_factor=gap[0] if gap else None,
            explanation=(
                f"No safe route for this departure: no route avoids No Travel "
                f"weather. {best.label} is the least bad, with "
                f"{best.no_travel_miles:.0f} No Travel miles. Consider a different "
                f"departure time."
            ),
        )

    warnings = []
    if best.coverage < 1:
        warnings.append(
            f"Forecast data covers {best.coverage:.0%} of {best.label}. "
            f"Risk on the remaining miles is unknown."
        )

    if len(ranked) == 1:
        factor, explanation = "only_option", (
            f"{best.label} is the only route available for this trip."
        )
    elif gap is None:
        factor, explanation = "tie", (
            f"{best.label} and {ranked[1].label} are equal on weather risk and "
            f"travel time."
        )
    else:
        factor, explanation = gap[0], f"{best.label} is recommended: {gap[1]}."

    return Recommendation(
        status=STATUS_RECOMMENDED,
        route_id=best.route_id,
        least_bad_route_id=None,
        ranked_route_ids=ranked_ids,
        deciding_factor=factor,
        explanation=explanation,
        warnings=warnings,
    )
