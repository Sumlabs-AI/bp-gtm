"""Static geography on Cells (Load Zone, county), from each Cell's center. Every run
recomputes every Cell (so a changed boundary file or rule takes effect) and writes only the
rows whose value changed."""

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.grid.zones import zone_for_points
from app.models import Cell
from app.need.markets import county_for_points


@dataclass
class EnrichmentReport:
    attribute: str
    processed: int
    assigned: int
    unknown: int
    by_value: dict[str, int]
    changed: int
    seconds: float


def _enrich(
    db: Session, attribute: str, rule: Callable[[pd.Series, pd.Series], pd.Series]
) -> EnrichmentReport:
    started = time.perf_counter()
    column = getattr(Cell, attribute)
    cells = pd.DataFrame(
        db.execute(select(Cell.h3_index, Cell.center_lat, Cell.center_lng, column)).all(),
        columns=["h3_index", "lat", "lng", "current"],
    )
    cells["value"] = rule(cells["lat"], cells["lng"])
    stale = cells[cells["value"].fillna("") != cells["current"].fillna("")]
    if len(stale):
        rows = stale[["h3_index", "value"]].rename(columns={"value": attribute})
        db.execute(update(Cell), rows.to_dict("records"))
    counts = Counter(v for v in cells["value"] if v is not None)
    return EnrichmentReport(
        attribute=attribute,
        processed=len(cells),
        assigned=sum(counts.values()),
        unknown=len(cells) - sum(counts.values()),
        by_value=dict(counts.most_common()),
        changed=len(stale),
        seconds=time.perf_counter() - started,
    )


def enrich_load_zones(db: Session) -> EnrichmentReport:
    """Each Cell's Load Zone, with the same rule Leads use. The caller commits."""
    return _enrich(db, "load_zone", zone_for_points)


def enrich_counties(db: Session) -> EnrichmentReport:
    """Each Cell's county (Census GEOID) from the Market county files. The caller commits."""
    return _enrich(db, "county_fips", county_for_points)
