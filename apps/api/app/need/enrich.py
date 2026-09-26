"""Static geography on Cells. Every run recomputes every Cell (so a changed zone file or
rule takes effect) and writes only the rows whose value changed."""

import time
from collections import Counter
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.grid.zones import zone_for_points
from app.models import Cell


@dataclass
class LoadZoneReport:
    processed: int
    assigned: int
    unknown: int
    by_zone: dict[str, int]
    changed: int
    seconds: float


def enrich_load_zones(db: Session) -> LoadZoneReport:
    """Set each Cell's load zone from its center, with the same rule Leads use.
    The caller commits."""
    started = time.perf_counter()
    cells = pd.DataFrame(
        db.execute(select(Cell.h3_index, Cell.center_lat, Cell.center_lng, Cell.load_zone)).all(),
        columns=["h3_index", "lat", "lng", "current"],
    )
    cells["zone"] = zone_for_points(cells["lat"], cells["lng"])
    stale = cells[cells["zone"].fillna("") != cells["current"].fillna("")]
    if len(stale):
        rows = stale[["h3_index", "zone"]].rename(columns={"zone": "load_zone"})
        db.execute(update(Cell), rows.to_dict("records"))
    by_zone = Counter(z for z in cells["zone"] if z is not None)
    return LoadZoneReport(
        processed=len(cells),
        assigned=sum(by_zone.values()),
        unknown=len(cells) - sum(by_zone.values()),
        by_zone=dict(by_zone.most_common()),
        changed=len(stale),
        seconds=time.perf_counter() - started,
    )
