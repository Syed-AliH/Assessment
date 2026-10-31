"""Turn whatever the router returns into up to three genuinely different routes."""
from datetime import datetime

from ..domain.geo import LatLon, haversine_miles, offset_from_midpoint, shared_fraction
from ..providers.base import ProviderError, RoutePlan, RoutingProvider

TARGET_ROUTES = 3
# Long-haul alternatives legitimately share most of their interstates.
MAX_SHARED_FRACTION = 0.95
MAX_DETOUR_RATIO = 1.5
VIA_OFFSET_RATIO = 0.12
VIA_OFFSET_MIN_MILES = 15.0
VIA_OFFSET_MAX_MILES = 120.0


def _add_if_distinct(chosen: list[RoutePlan], candidate: RoutePlan) -> None:
    if len(chosen) >= TARGET_ROUTES:
        return
    if all(
        shared_fraction(candidate.points, route.points) <= MAX_SHARED_FRACTION
        for route in chosen
    ):
        chosen.append(candidate)


def generate_routes(
    provider: RoutingProvider,
    origin: LatLon,
    destination: LatLon,
    departure: datetime | None,
    gross_weight_lb: float,
) -> list[RoutePlan]:
    """Fastest first. Fewer than three means no more distinct routes exist nearby."""
    chosen: list[RoutePlan] = []
    for plan in provider.routes(origin, destination, departure, gross_weight_lb):
        _add_if_distinct(chosen, plan)

    if len(chosen) < TARGET_ROUTES:
        straight = haversine_miles(origin, destination)
        offset = min(
            max(straight * VIA_OFFSET_RATIO, VIA_OFFSET_MIN_MILES), VIA_OFFSET_MAX_MILES
        )
        longest_allowed = chosen[0].length_miles * MAX_DETOUR_RATIO
        for side in (1, -1):
            if len(chosen) >= TARGET_ROUTES:
                break
            via = offset_from_midpoint(origin, destination, side * offset)
            try:
                plans = provider.routes(origin, destination, departure, gross_weight_lb, via=via)
            except ProviderError:
                continue  # A failed extra option should not cost the ones we have.
            for plan in plans:
                if plan.length_miles <= longest_allowed:
                    _add_if_distinct(chosen, plan)

    return sorted(chosen, key=lambda route: route.travel_seconds)
