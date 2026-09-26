"""Cells in Postgres: seed from a shape, query by viewport."""

import time
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import geo
from app.models import Cell
from app.need.config import need

# Rows per INSERT: 5 bind parameters each, well under Postgres' 65,535 limit.
BATCH = 5_000


@dataclass
class SeedReport:
    resolution: int
    generated: int
    inserted: int
    existing: int
    seconds: float


def _row(cell: str) -> dict:
    lat, lng = geo.cell_to_center(cell)
    ring = geo.cell_to_polygon(cell)["coordinates"][0]
    wkt = "POLYGON((" + ", ".join(f"{x} {y}" for x, y in ring) + "))"
    return {
        "h3_index": cell,
        "resolution": geo.cell_resolution(cell),
        "center_lat": lat,
        "center_lng": lng,
        "geometry": f"SRID=4326;{wkt}",
    }


def seed_polygon(db: Session, geometry: dict) -> SeedReport:
    """Insert the Cells covering a GeoJSON (Multi)Polygon; existing Cells are left alone.
    The caller commits."""
    started = time.perf_counter()
    resolution = need.h3_resolution
    cells = sorted(geo.polygon_to_cells(geometry, resolution))
    inserted = 0
    for i in range(0, len(cells), BATCH):
        rows = [_row(c) for c in cells[i : i + BATCH]]
        stmt = insert(Cell).values(rows).on_conflict_do_nothing(index_elements=["h3_index"])
        inserted += len(db.execute(stmt.returning(Cell.h3_index)).all())
    return SeedReport(
        resolution=resolution,
        generated=len(cells),
        inserted=inserted,
        existing=len(cells) - inserted,
        seconds=time.perf_counter() - started,
    )


def cells_in_viewport(
    db: Session, west: float, south: float, east: float, north: float, limit: int
) -> list[Cell] | None:
    """Cells intersecting the box, or None when there are more than `limit`."""
    box = func.ST_MakeEnvelope(west, south, east, north, 4326)
    rows = db.scalars(
        select(Cell).where(func.ST_Intersects(Cell.geometry, box)).limit(limit + 1)
    ).all()
    return None if len(rows) > limit else list(rows)


def get_cell(db: Session, h3_index: str) -> Cell | None:
    return db.get(Cell, h3_index)
