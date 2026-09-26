"""Baseline Need: how much structural reason a place has to benefit from backup power.

A union-style aggregation of two inputs, O = Observed Outage Exposure (county) and
W = Weather Need Component (res-6 storms + county temperature):

    raw = 100 × (1 − (1 − O/100) × (1 − W/100))

It's deterministic and not a probability: "at least one strong structural reason". The
inputs are complementary across Texas (rank correlation −0.38; most counties are high on
one, low on the other), so a mean would push one-sided places to the middle. raw is then
ranked against a statewide Reference Population, every Texas res-6 cell with the same
inputs computed the same way, so Baseline Need is a Texas percentile.

Utility Reliability Need is not an input (no defensible statewide Cell → utility mapping);
it's returned as context.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import geo
from app.models import (
    BaselineNeedReference,
    Cell,
    CellBaselineNeed,
    CountyOutageFeatures,
    CountyTemperatureFeatures,
    StormFeatures,
)
from app.need.components import mean_of_present, replace_rows

DRIVER_MARGIN = 10.0  # inputs within this many points: "both"
METHOD = (
    "union-style soft-OR of Observed Outage Exposure and Weather Need, "
    "ranked against Texas res-6 reference"
)
LIMITATIONS = [
    "Temperature Extremes is dry-bulb only (no humidity or heat index): humid heat, e.g. "
    "Houston, is under-rated.",
    "Outage input is county-level (every Cell in a county shares it).",
    "Utility reliability is context only, not part of the combination.",
]
NO_OUTAGE = "No Observed Outage Exposure for this county: Baseline Need uses Weather Need only"
NO_WEATHER = "No Weather Need here: Baseline Need uses Observed Outage Exposure only"


def soft_or(o: float | None, w: float | None) -> float | None:
    """Union-style combination on 0-100; a missing input counts as 0 (the other stands)."""
    if o is None and w is None:
        return None
    return round(100 * (1 - (1 - (o or 0) / 100) * (1 - (w or 0) / 100)), 2)


def dominant_driver(o: float | None, w: float | None) -> str | None:
    if o is None and w is None:
        return None
    if o is None or (w is not None and w - o > DRIVER_MARGIN):
        return "weather"
    if w is None or o - w > DRIVER_MARGIN:
        return "outage"
    return "both"


def reference_percentile(value: float | None, reference: np.ndarray) -> float | None:
    """Midrank percentile of `value` within the sorted reference distribution."""
    if value is None or len(reference) == 0:
        return None
    below = np.searchsorted(reference, value, side="left")
    ties = np.searchsorted(reference, value, side="right") - below
    return round(float((below + ties / 2) / len(reference) * 100), 2)


def _inputs(storm: float | None, county: str | None, outage: dict, temperature: dict) -> tuple:
    o = outage.get(county)
    w = mean_of_present(storm, temperature.get(county))
    return o, w


@dataclass
class BaselineReport:
    reference_cells: int
    reference_without_county: int
    cells: int
    cells_scored: int


def compute_baseline(
    db: Session, county_of: Callable[[list[str]], dict[str, str | None]]
) -> BaselineReport:
    """Rebuild the statewide reference and every Cell's Baseline Need. `county_of` maps res-6
    cells to the Census county containing their center. The caller commits."""
    now = datetime.now(UTC)
    outage = {c.county_fips: c.observed_exposure for c in db.scalars(select(CountyOutageFeatures))}
    temperature = {
        t.county_fips: t.temperature_exposure for t in db.scalars(select(CountyTemperatureFeatures))
    }
    storms = {s.h3_index: s.storm_exposure for s in db.scalars(select(StormFeatures))}
    counties = county_of(list(storms))

    reference = []
    for h6, storm in storms.items():
        o, w = _inputs(storm, counties.get(h6), outage, temperature)
        reference.append(
            {
                "h3_index": h6,
                "county_fips": counties.get(h6),
                "outage_input": o,
                "weather_input": w,
                "raw": soft_or(o, w),
            }
        )
    replace_rows(db, BaselineNeedReference, pd.DataFrame(reference), now)
    distribution = np.sort(np.array([r["raw"] for r in reference if r["raw"] is not None]))

    rows = []
    for cell in db.scalars(select(Cell)):
        storm = storms.get(geo.cell_to_parent(cell.h3_index, 6))
        o, w = _inputs(storm, cell.county_fips, outage, temperature)
        raw = soft_or(o, w)
        notes = []
        if o is None and w is not None:
            notes.append(NO_OUTAGE)
        if w is None and o is not None:
            notes.append(NO_WEATHER)
        rows.append(
            {
                "h3_index": cell.h3_index,
                "outage_input": o,
                "weather_input": w,
                "raw": raw,
                "baseline_need": reference_percentile(raw, distribution),
                "dominant_driver": dominant_driver(o, w),
                "notes": notes,
            }
        )
    replace_rows(db, CellBaselineNeed, pd.DataFrame(rows), now)
    return BaselineReport(
        reference_cells=len(reference),
        reference_without_county=sum(1 for r in reference if r["county_fips"] is None),
        cells=len(rows),
        cells_scored=sum(1 for r in rows if r["baseline_need"] is not None),
    )


def baseline_components(db: Session, cells: list[Cell]) -> dict[str, CellBaselineNeed | None]:
    rows = db.scalars(
        select(CellBaselineNeed).where(CellBaselineNeed.h3_index.in_([c.h3_index for c in cells]))
    )
    found = {r.h3_index: r for r in rows}
    return {c.h3_index: found.get(c.h3_index) for c in cells}
