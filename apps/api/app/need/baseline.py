"""Baseline Need: how much structural reason a place has to benefit from backup power.

A union-style aggregation of two inputs, O = Observed Outage Exposure (county) and
W = Weather Need Component (res-6 storms + county temperature):

    raw = 100 × (1 − (1 − O/100) × (1 − W/100))

It's deterministic and not a probability: "at least one strong structural reason". The
inputs are complementary across Texas (rank correlation −0.38; most counties are high on
one, low on the other), so a mean would push one-sided places to the middle. raw is then
ranked against a statewide Reference Population, every Texas res-6 cell with the same
inputs computed the same way, so Baseline Need is a Texas percentile (of land area).

Utility Reliability Need is not an input (no defensible statewide Cell → utility mapping);
it's returned as context. Baseline Need is not Live Need and not the Propensity Score.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

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
from app.need.config import baseline as config

Driver = Literal["outage", "weather", "both"]
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
NO_STORM = "No Storm Exposure here: Weather Need uses Temperature Extremes only"


def soft_or(o: float | None, w: float | None) -> float | None:
    """Union-style combination on 0-100; a missing input counts as 0 (the other stands)."""
    if o is None and w is None:
        return None
    return round(100 * (1 - (1 - (o or 0) / 100) * (1 - (w or 0) / 100)), 2)


def dominant_driver(o: float | None, w: float | None) -> Driver | None:
    if o is None and w is None:
        return None
    if o is None or (w is not None and w - o > config.driver_margin):
        return "weather"
    if w is None or o - w > config.driver_margin:
        return "outage"
    return "both"


def reference_percentile(value: float | None, reference: np.ndarray) -> float | None:
    """Midrank percentile of `value` within the sorted reference distribution: the same
    midrank rule as app.need.percentile, for a value that is not itself in the reference."""
    if value is None or len(reference) == 0:
        return None
    below = np.searchsorted(reference, value, side="left")
    ties = np.searchsorted(reference, value, side="right") - below
    return round(float((below + ties / 2) / len(reference) * 100), 2)


def _inputs(
    storm: float | None,
    county: str | None,
    outage: dict[str, float | None],
    temperature: dict[str, float | None],
) -> tuple[float | None, float | None]:
    """(O, W) for a place: the same definitions for Cells and the reference."""
    return outage.get(county), mean_of_present(storm, temperature.get(county))


@dataclass
class BaselineReport:
    reference_cells: int
    reference_ranked: int
    reference_without_county: int  # offshore / edge: excluded, not scored differently
    reference_without_outage: int  # county outside the outage Reference Population
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
    storms = dict(db.execute(select(StormFeatures.h3_index, StormFeatures.storm_exposure)).all())
    counties = county_of(list(storms))

    reference = []
    for h6, storm in storms.items():
        county = counties.get(h6)
        o, w = _inputs(storm, county, outage, temperature)
        # A cell in no county has no temperature, so its W would be storm-only: a different
        # definition. It's recorded and counted but not ranked.
        raw = soft_or(o, w) if county else None
        reference.append(
            {
                "h3_index": h6,
                "county_fips": county,
                "outage_input": o,
                "weather_input": w,
                "raw": raw,
            }
        )
    replace_rows(db, BaselineNeedReference, pd.DataFrame(reference), now)
    distribution = np.sort([r["raw"] for r in reference if r["raw"] is not None])

    cells = db.execute(select(Cell.h3_index, Cell.county_fips)).all()
    rows = []
    for h3_index, county in cells:
        storm = storms.get(geo.cell_to_parent(h3_index, 6))
        o, w = _inputs(storm, county, outage, temperature)
        raw = soft_or(o, w)
        notes = []
        if storm is None and w is not None:
            notes.append(NO_STORM)
        if o is None and w is not None:
            notes.append(NO_OUTAGE)
        if w is None and o is not None:
            notes.append(NO_WEATHER)
        rows.append(
            {
                "h3_index": h3_index,
                "outage_input": o,
                "weather_input": w,
                "raw": raw,
                "dominant_driver": dominant_driver(o, w),
                "notes": notes,
            }
        )
    frame = pd.DataFrame(rows)
    if not frame.empty:  # vectorized midrank percentile against the reference
        raw = frame["raw"].astype(float).to_numpy()
        below = np.searchsorted(distribution, raw, side="left")
        ties = np.searchsorted(distribution, raw, side="right") - below
        pct = np.round((below + ties / 2) / max(len(distribution), 1) * 100, 2)
        frame["baseline_need"] = np.where(np.isnan(raw) | (len(distribution) == 0), np.nan, pct)
    replace_rows(db, CellBaselineNeed, frame, now)
    return BaselineReport(
        reference_cells=len(reference),
        reference_ranked=len(distribution),
        reference_without_county=sum(1 for r in reference if r["county_fips"] is None),
        reference_without_outage=sum(
            1 for r in reference if r["county_fips"] and r["outage_input"] is None
        ),
        cells=len(rows),
        cells_scored=int(frame["baseline_need"].notna().sum()) if not frame.empty else 0,
    )


def baseline_components(db: Session, cells: list[Cell]) -> dict[str, CellBaselineNeed | None]:
    rows = db.scalars(
        select(CellBaselineNeed).where(CellBaselineNeed.h3_index.in_([c.h3_index for c in cells]))
    )
    found = {r.h3_index: r for r in rows}
    return {c.h3_index: found.get(c.h3_index) for c in cells}
