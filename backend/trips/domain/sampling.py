"""Place checkpoints along a route and estimate when the truck reaches them."""
from bisect import bisect_right
from dataclasses import dataclass

from .geo import LatLon, cumulative_miles


@dataclass(frozen=True)
class TimingAnchor:
    """A point on the route with a known elapsed time from departure."""

    miles: float
    seconds: float


@dataclass(frozen=True)
class Checkpoint:
    index: int
    miles: float
    lat: float
    lon: float
    eta_seconds: float
    represented_miles: float


def _interpolate(x: float, xs: list[float], ys: list[float]) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect_right(xs, x)
    span = xs[i] - xs[i - 1]
    if span <= 0:
        return ys[i]
    return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - xs[i - 1]) / span


def _clean_anchors(
    anchors: list[TimingAnchor], total_miles: float, total_seconds: float
) -> tuple[list[float], list[float]]:
    """Pin anchors to the route's ends and force time to be non-decreasing."""
    miles, seconds = [0.0], [0.0]
    for anchor in sorted(anchors, key=lambda a: a.miles):
        if 0 < anchor.miles < total_miles and anchor.miles > miles[-1]:
            miles.append(anchor.miles)
            seconds.append(min(max(anchor.seconds, seconds[-1]), total_seconds))
    miles.append(total_miles)
    seconds.append(total_seconds)
    return miles, seconds


def checkpoint_miles(total_miles: float, interval_miles: float) -> list[float]:
    """Every interval from the origin, plus the destination."""
    if total_miles <= 0:
        raise ValueError("route length must be positive")
    if interval_miles <= 0:
        raise ValueError("sampling interval must be positive")
    positions = []
    position = 0.0
    while position < total_miles:
        positions.append(position)
        position += interval_miles
    positions.append(total_miles)
    return positions


def build_checkpoints(
    points: list[LatLon],
    total_miles: float,
    total_seconds: float,
    interval_miles: float,
    anchors: list[TimingAnchor] | None = None,
) -> list[Checkpoint]:
    """Checkpoints for one route.

    `total_miles` is the routing provider's figure. The geometry's own length
    differs slightly, so it is scaled to match. Each checkpoint represents the
    stretch between the midpoints to its neighbours, which makes represented
    miles add up to exactly the route length. Without `anchors`, ETA assumes
    constant speed.
    """
    if len(points) < 2:
        raise ValueError("route geometry needs at least two points")

    along = cumulative_miles(points)
    if along[-1] <= 0:
        raise ValueError("route geometry has no length")
    scale = total_miles / along[-1]
    along = [miles * scale for miles in along]
    lats = [point[0] for point in points]
    lons = [point[1] for point in points]
    anchor_miles, anchor_seconds = _clean_anchors(anchors or [], total_miles, total_seconds)

    positions = checkpoint_miles(total_miles, interval_miles)
    edges = [0.0]
    edges += [(a + b) / 2 for a, b in zip(positions, positions[1:])]
    edges.append(total_miles)

    return [
        Checkpoint(
            index=i,
            miles=miles,
            lat=_interpolate(miles, along, lats),
            lon=_interpolate(miles, along, lons),
            eta_seconds=_interpolate(miles, anchor_miles, anchor_seconds),
            represented_miles=edges[i + 1] - edges[i],
        )
        for i, miles in enumerate(positions)
    ]
