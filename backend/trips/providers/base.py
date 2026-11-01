"""What the app needs from outside services. Nothing here knows a vendor."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from ..domain.geo import LatLon
from ..domain.sampling import TimingAnchor


class ProviderError(Exception):
    """An outside service could not give a usable answer."""


class NoRouteFound(ProviderError):
    pass


class RateLimited(ProviderError):
    pass


class UpstreamUnavailable(ProviderError):
    pass


class InvalidRequest(ProviderError):
    """The request cannot be answered, such as a departure already in the past."""


@dataclass(frozen=True)
class Place:
    label: str
    lat: float
    lon: float


@dataclass(frozen=True)
class RoutePlan:
    points: list[LatLon]
    length_miles: float
    travel_seconds: float
    departure: datetime  # timezone-aware, in the origin's zone
    anchors: list[TimingAnchor] = field(default_factory=list)
    traffic_delay_seconds: float = 0
    non_truck_miles: float = 0


class RoutingProvider(Protocol):
    def routes(
        self,
        origin: LatLon,
        destination: LatLon,
        departure: datetime | None,
        gross_weight_lb: float,
        via: LatLon | None = None,
    ) -> list[RoutePlan]:
        """Fastest first. `departure` is naive origin-local time; None means now."""


class Geocoder(Protocol):
    def search(self, query: str) -> list[Place]:
        ...

