"""Need Engine Cells end to end: geometry -> seeded Cells in PostGIS -> HTTP API."""

from shapely.geometry import shape

from app import geo
from app.db import SessionLocal
from app.need.config import need
from app.need.store import seed_polygon

LAT, LNG = 29.7604, -95.3698  # Houston City Hall


def square(lng: float, lat: float, d: float) -> dict:
    return {
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


def seed(geometry: dict):
    with SessionLocal() as db:
        report = seed_polygon(db, geometry)
        db.commit()
    return report


def test_seeding_is_idempotent():
    first = seed(square(LNG, LAT, 0.02))
    assert first.resolution == 8
    assert first.generated > 0
    assert (first.inserted, first.existing) == (first.generated, 0)

    again = seed(square(LNG, LAT, 0.02))
    assert again.generated == first.generated
    assert (again.inserted, again.existing) == (0, first.generated)

    # An overlapping area only adds the Cells that weren't there yet.
    wider = seed(square(LNG, LAT, 0.04))
    assert wider.existing == first.generated
    assert wider.inserted == wider.generated - first.generated


def bbox(west: float, south: float, east: float, north: float) -> str:
    return f"{west},{south},{east},{north}"


def test_viewport_returns_only_cells_in_view(client):
    # Two small patches ~40 km apart: downtown Houston and west of it.
    seed(square(LNG, LAT, 0.01))
    seed(square(LNG - 0.4, LAT, 0.01))

    downtown = client.get(
        "/need/cells", params={"bbox": bbox(LNG - 0.05, LAT - 0.05, LNG + 0.05, LAT + 0.05)}
    )
    assert downtown.status_code == 200
    ids = {f["id"] for f in downtown.json()["features"]}
    assert geo.latlng_to_cell(LAT, LNG) in ids
    assert geo.latlng_to_cell(LAT, LNG - 0.4) not in ids

    both = client.get(
        "/need/cells", params={"bbox": bbox(LNG - 0.5, LAT - 0.05, LNG + 0.05, LAT + 0.05)}
    )
    assert len(both.json()["features"]) > len(ids)

    empty = client.get("/need/cells", params={"bbox": bbox(-97.8, 30.2, -97.7, 30.3)})  # Austin
    assert empty.json() == {"type": "FeatureCollection", "features": []}

    # A box clipping just the edge of a Cell still returns that Cell.
    ring = geo.cell_to_polygon(geo.latlng_to_cell(LAT, LNG))["coordinates"][0]
    x, y = max(ring, key=lambda p: p[0])  # easternmost vertex
    edge = client.get("/need/cells", params={"bbox": bbox(x - 1e-4, y - 1e-4, x + 1e-4, y + 1e-4)})
    assert geo.latlng_to_cell(LAT, LNG) in {f["id"] for f in edge.json()["features"]}


def test_cells_are_valid_geojson(client):
    seed(square(LNG, LAT, 0.01))
    body = client.get("/need/cells", params={"bbox": bbox(-96, 29, -95, 30)}).json()
    assert body["type"] == "FeatureCollection"
    assert body["features"]
    for feature in body["features"]:
        assert feature["type"] == "Feature"
        assert feature["id"] == feature["properties"]["h3"]
        assert feature["properties"]["needScore"] is None
        assert feature["geometry"]["type"] == "Polygon"
        ring = feature["geometry"]["coordinates"][0]
        assert ring[0] == ring[-1] and len(ring) == 7
        assert all(-96 < lng < -95 and 29 < lat < 30 for lng, lat in ring)  # [lng, lat]
        assert shape(feature["geometry"]).is_valid


def test_too_many_cells_asks_to_zoom_in(client, monkeypatch):
    report = seed(square(LNG, LAT, 0.02))
    view = {"bbox": bbox(-96, 29, -95, 30)}
    monkeypatch.setattr(need, "viewport_max_cells", report.generated)
    assert client.get("/need/cells", params=view).status_code == 200

    monkeypatch.setattr(need, "viewport_max_cells", report.generated - 1)
    response = client.get("/need/cells", params=view)
    assert response.status_code == 400
    assert response.json() == {
        "detail": "Viewport contains too many H3 cells. Zoom in to continue."
    }


def test_bad_bbox_is_rejected(client):
    for value in ("-96,29,-95", "a,b,c,d", "-95,29,-96,30", "-96,30,-95,29", "-200,29,-95,30"):
        assert client.get("/need/cells", params={"bbox": value}).status_code == 422
    assert client.get("/need/cells").status_code == 422


def test_cell_detail(client):
    seed(square(LNG, LAT, 0.01))
    cell = geo.latlng_to_cell(LAT, LNG)
    center_lat, center_lng = geo.cell_to_center(cell)

    assert client.get(f"/need/cells/{cell}").json() == {
        "h3": cell,
        "resolution": 8,
        "center": {"lat": center_lat, "lng": center_lng},
        "needScore": None,
        "components": {},
    }
    # Valid H3 index, but not seeded (Austin).
    assert client.get(f"/need/cells/{geo.latlng_to_cell(30.27, -97.74)}").status_code == 404
    assert client.get("/need/cells/not-a-cell").status_code == 404
