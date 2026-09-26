"""Shared H3 contract: map points and shapes onto Cells.

Pure functions, no database or web imports, so other workstreams (e.g. the ML propensity
model mapping permits) can import this directly. Cells are H3 indexes as 15-character
lowercase hex strings. GeoJSON geometries use [lng, lat] order; function arguments and
return values that are plain pairs use (lat, lng).

Polygon coverage follows H3's center rule: a Cell belongs to a shape when its center is
inside it, so edge Cells can extend past the boundary.
"""

import h3

# The resolution every Need workstream joins on (~0.74 km² hexagons).
RESOLUTION = 8


def latlng_to_cell(lat: float, lng: float, resolution: int = RESOLUTION) -> str:
    return h3.latlng_to_cell(lat, lng, resolution)


def cell_to_center(cell: str) -> tuple[float, float]:
    """(lat, lng) of the Cell's center."""
    return h3.cell_to_latlng(cell)


def cell_resolution(cell: str) -> int:
    return h3.get_resolution(cell)


def cell_to_polygon(cell: str) -> dict:
    """GeoJSON Polygon of the Cell, closed ring in [lng, lat] order."""
    ring = [[lng, lat] for lat, lng in h3.cell_to_boundary(cell)]
    return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}


def polygon_to_cells(geometry: dict, resolution: int = RESOLUTION) -> set[str]:
    """Cells whose centers fall inside a GeoJSON Polygon or MultiPolygon."""
    return set(h3.geo_to_cells(geometry, resolution))


def is_cell(value: str) -> bool:
    try:
        return h3.is_valid_cell(value)
    except (TypeError, ValueError):
        return False
