"""Grid cells covering the corridor around a set of routes.

Cells sit on a fixed global grid, so overlapping trips reuse cached forecasts.
The finest step that fits the cell budget wins: each cell is one forecast
location, and the free weather quota is the real constraint here.
"""
import math
from dataclasses import dataclass

from .geo import MILES_PER_DEGREE_LAT, LatLon, densify

GRID_STEPS_DEGREES = (0.125, 0.25, 0.5, 0.75)
DEFAULT_HALF_WIDTH_MILES = 30.0
DEFAULT_MAX_CELLS = 300


@dataclass(frozen=True)
class Corridor:
    step: float
    cells: list[LatLon]  # cell centres


def _cells_for_step(
    routes: list[list[LatLon]], step: float, half_width_miles: float
) -> set[tuple[int, int]]:
    spacing = step * MILES_PER_DEGREE_LAT / 2
    reach_lat = half_width_miles / MILES_PER_DEGREE_LAT
    cells: set[tuple[int, int]] = set()
    for route in routes:
        for lat, lon in densify(route, spacing):
            miles_per_degree_lon = MILES_PER_DEGREE_LAT * max(
                math.cos(math.radians(lat)), 0.05
            )
            reach_lon = half_width_miles / miles_per_degree_lon
            for row in range(
                math.floor((lat - reach_lat) / step),
                math.ceil((lat + reach_lat) / step) + 1,
            ):
                for column in range(
                    math.floor((lon - reach_lon) / step),
                    math.ceil((lon + reach_lon) / step) + 1,
                ):
                    d_lat = ((row + 0.5) * step - lat) * MILES_PER_DEGREE_LAT
                    d_lon = ((column + 0.5) * step - lon) * miles_per_degree_lon
                    if d_lat * d_lat + d_lon * d_lon <= half_width_miles**2:
                        cells.add((row, column))
    return cells


def build_corridor(
    routes: list[list[LatLon]],
    half_width_miles: float = DEFAULT_HALF_WIDTH_MILES,
    max_cells: int = DEFAULT_MAX_CELLS,
) -> Corridor:
    if not routes:
        raise ValueError("corridor needs at least one route")
    for step in GRID_STEPS_DEGREES:
        cells = _cells_for_step(routes, step, half_width_miles)
        if len(cells) <= max_cells:
            break
    # Past the coarsest step, keep the cells: a corridor with gaps would imply
    # calm weather where nothing was sampled.
    return Corridor(
        step=step,
        cells=[
            ((row + 0.5) * step, (column + 0.5) * step)
            for row, column in sorted(cells)
        ],
    )
