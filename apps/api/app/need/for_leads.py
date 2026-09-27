"""What the leads side reads from the Need Engine, keyed by a home's h3_index.

Cell scores are never copied onto leads: everything here is read at request time, so a
recomputed Cell or an expired alert shows up on the next request.
"""

from dataclasses import dataclass
from datetime import datetime
from functools import cached_property

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Cell, CellBaselineNeed, CellPropensity, Lead, Property
from app.need.config import NEED_BANDS, NEED_BANDS_TOP
from app.need.config import opportunity as opportunity_config
from app.need.live.forecast_store import active_forecast, most_severe_level
from app.need.live.grid import grid_live, is_stale, latest_condition
from app.need.live.store import active_alerts
from app.need.ml import latest_propensity
from app.need.opportunity import LeadCells, opportunity_score, opportunity_sql, pick_lead_cells
from app.need.timing import timing_by_cell, timing_sql


def latest_propensity_subquery():
    """h3_index -> propensity_score of the latest prediction (as app.need.ml.latest_propensity),
    as a subquery to join and sort on."""
    return (
        select(CellPropensity.h3_index, CellPropensity.propensity_score)
        .distinct(CellPropensity.h3_index)
        .order_by(
            CellPropensity.h3_index,
            CellPropensity.scored_at.desc(),
            CellPropensity.imported_at.desc(),
        )
        .subquery()
    )


def cells_in_bands(db: Session, bands: list[str]) -> set[str]:
    """Cells whose Baseline Need falls in any of the named bands (top band includes 100)."""
    need = CellBaselineNeed.baseline_need
    ranges = [
        (need >= lo) & ((need <= hi) if band == NEED_BANDS_TOP else (need < hi))
        for band, (lo, hi) in ((b, NEED_BANDS[b]) for b in bands)
    ]
    return set(db.scalars(select(CellBaselineNeed.h3_index).where(or_(*ranges))))


@dataclass(frozen=True)
class CellRef:
    """The two Cell attributes the live readers need; loading 8.7k full rows with their
    PostGIS geometry per request is not."""

    h3_index: str
    load_zone: str | None


class LiveCells:
    """The Cells under each kind of live signal at `now`, each computed at most once per
    request (the filters and the summary both ask)."""

    def __init__(self, db: Session, now: datetime) -> None:
        self.db, self.now = db, now

    @cached_property
    def all(self) -> list[CellRef]:
        return [CellRef(h, z) for h, z in self.db.execute(select(Cell.h3_index, Cell.load_zone))]

    @cached_property
    def alert(self) -> set[str]:
        return {h for h, s in active_alerts(self.db, self.all, self.now).items() if s}

    @cached_property
    def forecast(self) -> set[str]:
        return {h for h, s in active_forecast(self.db, self.all, self.now).items() if s}

    @cached_property
    def grid_stress(self) -> set[str]:
        """Reliability stress applies to every Cell, a zone price spike to its zone's Cells."""
        return {h for h, g in grid_live(self.db, self.all, self.now).items() if g["stressSignals"]}

    @cached_property
    def lead(self) -> dict[str, LeadCells]:
        return lead_cells(self.db, self.now)


def lead_cells(db: Session, now: datetime) -> dict[str, LeadCells]:
    """county -> its Lead Cells and cutoff at `now` (Timing included), see pick_lead_cells."""
    propensity = latest_propensity_subquery()
    timing = timing_sql(db, now)
    multiplier = func.coalesce(timing.c.multiplier, 1.0) if timing is not None else 1.0
    score = opportunity_sql(
        propensity.c.propensity_score, CellBaselineNeed.baseline_need, multiplier
    )
    query = (
        select(Property.county, Property.h3_index, func.count(), score)
        .select_from(Lead)
        .join(Property)
        .outerjoin(CellBaselineNeed, CellBaselineNeed.h3_index == Property.h3_index)
        .outerjoin(propensity, propensity.c.h3_index == Property.h3_index)
        .where(Property.h3_index.is_not(None))
        .group_by(Property.county, Property.h3_index, score)
    )
    if timing is not None:
        query = query.outerjoin(timing, timing.c.h3_index == Property.h3_index)
    rows = [(c, h, n, float(s) if s is not None else None) for c, h, n, s in db.execute(query)]
    return pick_lead_cells(rows, opportunity_config.lead_share)


def cell_blocks(db: Session, h3s: set[str], now: datetime) -> dict[str, dict]:
    """h3_index -> what a lead row shows about its Cell (a few queries, whatever the count)."""
    cells = [
        CellRef(h, z)
        for h, z in db.execute(select(Cell.h3_index, Cell.load_zone).where(Cell.h3_index.in_(h3s)))
    ]
    if not cells:
        return {}
    ids = [c.h3_index for c in cells]
    needs = dict(
        db.execute(
            select(CellBaselineNeed.h3_index, CellBaselineNeed.baseline_need).where(
                CellBaselineNeed.h3_index.in_(ids)
            )
        ).all()
    )
    propensity = latest_propensity(db, ids)
    alerts = active_alerts(db, cells, now)
    forecasts = active_forecast(db, cells, now)
    grid = grid_live(db, cells, now)
    timing = timing_by_cell(db, now, cells)
    return {
        c.h3_index: {
            "baseline_need": needs.get(c.h3_index),
            "propensity_score": (
                prop := p.propensity_score if (p := propensity.get(c.h3_index)) else None
            ),
            "opportunity_score": opportunity_score(
                prop, needs.get(c.h3_index), timing[c.h3_index].multiplier
            ),
            "timing": timing[c.h3_index].multiplier,
            "active_alerts": len(alerts[c.h3_index]),
            "forecast_level": most_severe_level(forecasts[c.h3_index]),
            "grid_stress_signals": len(grid[c.h3_index]["stressSignals"]),
        }
        for c in cells
    }


def grid_state(db: Session, now: datetime) -> str | None:
    row = latest_condition(db, now)
    return None if row is None or is_stale(row, now) else row.state
