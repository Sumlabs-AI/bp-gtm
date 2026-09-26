"""The shared H3 contract (app.geo): what the ML workstream relies on to map points to Cells."""

import math

from shapely.geometry import Point, shape

from app import geo

# Houston City Hall.
HOUSTON = (29.7604, -95.3698)


def km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    (lat1, lng1), (lat2, lng2) = a, b
    x = math.radians(lng2 - lng1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return 6371 * math.hypot(x, y)


def test_latlng_maps_to_a_resolution_8_cell():
    cell = geo.latlng_to_cell(*HOUSTON)
    assert isinstance(cell, str)
    assert len(cell) == 15
    int(cell, 16)  # canonical lowercase hex string
    assert cell == cell.lower()
    assert geo.cell_resolution(cell) == 8
    # Res-8 hexagon edge is ~0.5 km, so the point is well within 1 km of the center.
    assert km_between(HOUSTON, geo.cell_to_center(cell)) < 1
    assert geo.latlng_to_cell(*geo.cell_to_center(cell)) == cell


def test_explicit_resolution():
    coarse = geo.latlng_to_cell(*HOUSTON, resolution=6)
    assert coarse != geo.latlng_to_cell(*HOUSTON)
    assert km_between(HOUSTON, geo.cell_to_center(coarse)) < 5


def test_cell_polygon_is_a_closed_hexagon_in_lng_lat_order():
    cell = geo.latlng_to_cell(*HOUSTON)
    polygon = geo.cell_to_polygon(cell)
    assert polygon["type"] == "Polygon"
    ring = polygon["coordinates"][0]
    assert len(ring) == 7
    assert ring[0] == ring[-1]
    assert len({tuple(p) for p in ring}) == 6
    lng, lat = ring[0]
    assert -96 < lng < -95 and 29 < lat < 30  # lng first
    assert shape(polygon).contains(Point(HOUSTON[1], HOUSTON[0]))


def test_polygon_to_cells_covers_the_polygon():
    # ~2 km square around City Hall.
    lat, lng = HOUSTON
    d = 0.01
    square = {
        "type": "Polygon",
        "coordinates": [
            [
                [lng - d, lat - d],
                [lng + d, lat - d],
                [lng + d, lat + d],
                [lng - d, lat + d],
                [lng - d, lat - d],
            ]
        ],
    }
    cells = geo.polygon_to_cells(square)
    assert geo.latlng_to_cell(*HOUSTON) in cells
    # A ~4.4 km² square holds a handful of ~0.74 km² res-8 cells.
    assert 3 <= len(cells) <= 12
    # Center-in-polygon rule: every returned Cell's center lies inside the square.
    area = shape(square)
    for cell in cells:
        c_lat, c_lng = geo.cell_to_center(cell)
        assert area.contains(Point(c_lng, c_lat))


def test_polygon_to_cells_accepts_multipolygons():
    lat, lng = HOUSTON
    d = 0.01

    def square(x: float) -> list:
        return [
            [
                [x - d, lat - d],
                [x + d, lat - d],
                [x + d, lat + d],
                [x - d, lat + d],
                [x - d, lat - d],
            ]
        ]

    west, east = square(lng - 0.2), square(lng + 0.2)
    multi = {"type": "MultiPolygon", "coordinates": [west, east]}
    cells = geo.polygon_to_cells(multi)
    west_cells = geo.polygon_to_cells({"type": "Polygon", "coordinates": west})
    east_cells = geo.polygon_to_cells({"type": "Polygon", "coordinates": east})
    assert cells == west_cells | east_cells
    assert west_cells and east_cells
