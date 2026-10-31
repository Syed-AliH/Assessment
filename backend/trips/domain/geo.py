"""Small spherical geometry helpers. Coordinates are (lat, lon) in degrees."""
import math

EARTH_RADIUS_MILES = 3958.7613
METERS_PER_MILE = 1609.344
MILES_PER_DEGREE_LAT = 69.055

LatLon = tuple[float, float]


def haversine_miles(a: LatLon, b: LatLon) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(h)))


def snap(value: float, step: float) -> float:
    """Round to a fixed grid so nearby points share one forecast lookup."""
    return round(round(value / step) * step, 6)


def snap_point(point: LatLon, step: float) -> LatLon:
    return snap(point[0], step), snap(point[1], step)


def coarsest_needed_step(
    points: list[LatLon], steps: tuple[float, ...], max_points: int
) -> float:
    """The finest grid step that keeps `points` to `max_points` unique cells."""
    for step in steps:
        if len({snap_point(point, step) for point in points}) <= max_points:
            return step
    return steps[-1]


def cumulative_miles(points: list[LatLon]) -> list[float]:
    totals = [0.0]
    for previous, current in zip(points, points[1:]):
        totals.append(totals[-1] + haversine_miles(previous, current))
    return totals


def densify(points: list[LatLon], spacing_miles: float) -> list[LatLon]:
    """Resample a polyline so vertices are about `spacing_miles` apart."""
    along = cumulative_miles(points)
    dense = [points[0]]
    next_mark = spacing_miles
    for i in range(1, len(points)):
        while next_mark <= along[i]:
            span = along[i] - along[i - 1]
            t = (next_mark - along[i - 1]) / span if span else 0.0
            a, b = points[i - 1], points[i]
            dense.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            next_mark += spacing_miles
    dense.append(points[-1])
    return dense


def shared_fraction(a: list[LatLon], b: list[LatLon], spacing_miles: float = 1.0) -> float:
    """How much of the shorter polyline runs along the other, from 0 to 1."""
    step = 0.02  # about a mile
    cells_a = {snap_point(p, step) for p in densify(a, spacing_miles)}
    cells_b = {snap_point(p, step) for p in densify(b, spacing_miles)}
    return len(cells_a & cells_b) / min(len(cells_a), len(cells_b))


def offset_from_midpoint(
    origin: LatLon, destination: LatLon, offset_miles: float
) -> LatLon:
    """A point beside the straight line's midpoint. The sign picks the side."""
    mid_lat = (origin[0] + destination[0]) / 2
    mid_lon = (origin[1] + destination[1]) / 2
    miles_per_lon = MILES_PER_DEGREE_LAT * math.cos(math.radians(mid_lat))
    north = (destination[0] - origin[0]) * MILES_PER_DEGREE_LAT
    east = (destination[1] - origin[1]) * miles_per_lon
    length = math.hypot(north, east) or 1.0
    return (
        mid_lat + (east / length) * offset_miles / MILES_PER_DEGREE_LAT,
        mid_lon - (north / length) * offset_miles / miles_per_lon,
    )


def simplify(points: list[LatLon], tolerance_degrees: float) -> list[LatLon]:
    """Iterative Douglas-Peucker. Keeps both ends."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    limit = tolerance_degrees**2
    while stack:
        first, last = stack.pop()
        ax, ay = points[first]
        bx, by = points[last]
        dx, dy = bx - ax, by - ay
        norm = dx * dx + dy * dy
        worst, worst_index = 0.0, -1
        for i in range(first + 1, last):
            px, py = points[i]
            t = ((px - ax) * dx + (py - ay) * dy) / norm if norm else 0.0
            t = max(0.0, min(1.0, t))
            ex, ey = px - (ax + t * dx), py - (ay + t * dy)
            distance = ex * ex + ey * ey
            if distance > worst:
                worst, worst_index = distance, i
        if worst > limit:
            keep[worst_index] = True
            stack.append((first, worst_index))
            stack.append((worst_index, last))
    return [point for point, kept in zip(points, keep) if kept]
