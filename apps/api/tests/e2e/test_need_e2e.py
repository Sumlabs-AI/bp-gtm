"""Need Engine Cells end to end: geometry -> seeded Cells in PostGIS -> HTTP API."""

import pandas as pd
from shapely.geometry import shape
from sqlalchemy import func, select, update

from app import geo
from app.db import SessionLocal
from app.grid.zones import zone_for_points
from app.models import Cell
from app.need.config import need
from app.need.enrich import enrich_load_zones
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
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Cell)) == first.generated

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
        "loadZone": None,  # set by enrichment, not by seeding
        "needScore": None,
        "components": {},
    }
    # Valid H3 index, but not seeded (Austin).
    assert client.get(f"/need/cells/{geo.latlng_to_cell(30.27, -97.74)}").status_code == 404
    assert client.get("/need/cells/not-a-cell").status_code == 404


AUSTIN = (30.2672, -97.7431)  # downtown, Austin Energy territory
GULF = (27.0, -94.0)  # offshore: no load zone


def enrich():
    with SessionLocal() as db:
        report = enrich_load_zones(db)
        db.commit()
    return report


def test_enrichment_assigns_each_cell_its_load_zone(client):
    houston = seed(square(LNG, LAT, 0.01)).generated
    austin = seed(square(AUSTIN[1], AUSTIN[0], 0.01)).generated
    gulf = seed(square(GULF[1], GULF[0], 0.01)).generated

    # Which zone each Cell gets is the shared rule's job (tests/test_grid_zones.py); here:
    # every Cell is processed, and a Cell outside every zone stays unknown (no fallback).
    report = enrich()
    assert report.processed == houston + austin + gulf
    assert (report.assigned, report.unknown) == (houston + austin, gulf)
    assert sum(report.by_value.values()) == report.assigned
    gulf_cell = client.get(f"/need/cells/{geo.latlng_to_cell(*GULF)}").json()
    assert gulf_cell["loadZone"] is None


def test_cells_use_the_shared_load_zone_rule(client):
    # Cells straddling the Austin Energy boundary, where the smallest-polygon rule matters.
    seed(square(-97.84, 30.2672, 0.06))
    enrich()
    features = client.get("/need/cells", params={"bbox": bbox(-98, 30.1, -97.7, 30.4)}).json()
    details = [client.get(f"/need/cells/{f['id']}").json() for f in features["features"]]
    centers = pd.DataFrame([d["center"] for d in details])
    expected = zone_for_points(centers["lat"], centers["lng"]).tolist()
    assert [d["loadZone"] for d in details] == expected
    assert {"LZ_AEN", "LZ_SOUTH"} <= set(expected)  # both sides of the boundary covered


def test_enrichment_recomputes_every_run(client):
    seed(square(LNG, LAT, 0.01))
    first = enrich()
    assert first.changed == first.processed

    again = enrich()
    assert again.changed == 0
    assert (again.assigned, again.by_value) == (first.assigned, first.by_value)

    # A stale zone (e.g. from an older zone file) is corrected, not kept.
    cell = geo.latlng_to_cell(LAT, LNG)
    with SessionLocal() as db:
        db.execute(update(Cell).where(Cell.h3_index == cell).values(load_zone="LZ_WEST"))
        db.commit()
    fixed = enrich()
    assert fixed.changed == 1
    assert client.get(f"/need/cells/{cell}").json()["loadZone"] == "LZ_HOUSTON"
