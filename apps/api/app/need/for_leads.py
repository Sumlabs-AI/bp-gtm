"""What the leads side reads from the Need Engine, keyed by a home's h3_index.

Cell scores are never copied onto leads: everything here is read at request time, so a
recomputed Cell or an expired alert shows up on the next request.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Cell, CellBaselineNeed
from app.need.config import NEED_BANDS
from app.need.live.forecast_store import active_forecast, most_severe_level
from app.need.live.grid import grid_live, is_stale, latest_condition
from app.need.live.store import active_alerts
from app.need.ml import latest_propensity


def cells_in_bands(db: Session, bands: list[str]) -> set[str]:
    """Cells whose Baseline Need falls in any of the named bands."""
    ranges = [NEED_BANDS[b] for b in bands]
    result = set()
    needs = dict(
        db.execute(select(CellBaselineNeed.h3_index, CellBaselineNeed.baseline_need)).all()
    )
    for h3, need in needs.items():
        if need is not None and any(lo <= need < hi for lo, hi in ranges):
            result.add(h3)
    return result


def _all_cells(db: Session) -> list[Cell]:
    return db.scalars(select(Cell)).all()


def cells_with_alert(db: Session, now: datetime) -> set[str]:
    cells = _all_cells(db)
    return {h for h, signals in active_alerts(db, cells, now).items() if signals}


def cells_with_forecast(db: Session, now: datetime) -> set[str]:
    cells = _all_cells(db)
    return {h for h, signals in active_forecast(db, cells, now).items() if signals}


def cells_with_grid_stress(db: Session, now: datetime) -> set[str]:
    """Reliability stress (reserves / margin) applies to every Cell; a zone price spike to
    the Cells of that zone. Reuses the live grid module's per-Cell reading."""
    cells = _all_cells(db)
    return {h for h, g in grid_live(db, cells, now).items() if g["stressSignals"]}


def cell_blocks(db: Session, h3s: set[str], now: datetime) -> dict[str, dict]:
    """h3_index -> what a lead row shows about its Cell (a few queries, whatever the count)."""
    cells = db.scalars(select(Cell).where(Cell.h3_index.in_(h3s))).all()
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
    return {
        c.h3_index: {
            "baseline_need": needs.get(c.h3_index),
            "propensity_score": p.propensity_score if (p := propensity.get(c.h3_index)) else None,
            "active_alerts": len(alerts[c.h3_index]),
            "forecast_level": most_severe_level(forecasts[c.h3_index]),
            "grid_stress_signals": len(grid[c.h3_index]["stressSignals"]),
        }
        for c in cells
    }


def grid_state(db: Session, now: datetime) -> str | None:
    row = latest_condition(db, now)
    return None if row is None or is_stale(row, now) else row.state
