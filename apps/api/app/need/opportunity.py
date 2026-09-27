"""Opportunity Score: one number per Cell from Propensity, Baseline Need and Timing (CONTEXT.md).

Opportunity = 100 x (Propensity / 100) ^ w_p x (Baseline Need / 100) ^ w_n x Timing,
with w_p + w_n = 1. The part before Timing (the base score) is 0-100; Timing (1.0-1.5,
app/need/timing.py) lifts a Cell for the weeks after a storm, so the score can reach 150 there.

A weighted geometric mean: a Cell needs both the right homes and a real reason for backup, and
a zero in either gives zero. It is a rank, not a probability: Propensity is a percentile within
its metro and Baseline Need a Texas percentile. Null when Propensity or Baseline Need is missing.
"""

from dataclasses import dataclass, field

from sqlalchemy import func

from app.need.config import opportunity as config

METHOD = (
    f"Weighted geometric mean of Propensity (weight {config.propensity_weight:g}) and "
    f"Baseline Need (weight {config.need_weight:g}), both 0-100, times Timing (1.0-1.5): "
    "0-100 normally, up to 150 in the weeks after a storm."
)
LIMITATIONS = [
    "A rank, not a probability: Propensity is ranked within its metro, Baseline Need across Texas.",
    "Inside one metro, Baseline Need varies little (county outage history, res-6 storms), "
    "so the order there is mostly Propensity.",
    "No Eligibility (Base service area) or Installable (share of homes meeting install "
    "requirements) factor yet: every Cell counts as eligible and installable.",
    "Timing comes from NWS Alerts only (no outage data yet), and moves the score week to week.",
    "Forecast Signals and ERCOT grid stress are not included.",
]


def opportunity_score(
    propensity: float | None, baseline_need: float | None, timing: float = 1.0
) -> float | None:
    if propensity is None or baseline_need is None:
        return None
    score = (
        100
        * (propensity / 100) ** config.propensity_weight
        * (baseline_need / 100) ** config.need_weight
        * timing
    )
    return round(score, 1)


@dataclass
class LeadCells:
    """A county's Lead Cells and the lowest Opportunity Score among them (its cutoff)."""

    cells: set[str] = field(default_factory=set)
    min_score: float = 0.0


def pick_lead_cells(
    cells: list[tuple[str, str, int, float | None]], share: float
) -> dict[str, LeadCells]:
    """county -> its Lead Cells, from (county, h3_index, homes, opportunity) rows.

    Walks each county's Cells from the highest Opportunity down, whole Cells, until they hold
    `share` of the county's homes (the Cell that crosses the line is in). Unscored Cells count
    toward the county's homes but are never Lead Cells."""
    totals: dict[str, int] = {}
    for county, _, homes, _ in cells:
        totals[county] = totals.get(county, 0) + homes
    ranked = sorted((c for c in cells if c[3] is not None), key=lambda c: (-c[3], c[1]))
    picked: dict[str, LeadCells] = {}
    held: dict[str, int] = {}
    for county, h3_index, homes, score in ranked:
        if held.get(county, 0) >= share * totals[county]:
            continue
        lead = picked.setdefault(county, LeadCells())
        lead.cells.add(h3_index)
        lead.min_score = score  # ranked high to low: the last one in is the lowest
        held[county] = held.get(county, 0) + homes
    return picked


def opportunity_sql(propensity, baseline_need, timing=1.0):
    """The same score as a SQL expression (for sorting); NULL when either input is NULL."""
    return (
        100
        * func.power(propensity / 100.0, config.propensity_weight)
        * func.power(baseline_need / 100.0, config.need_weight)
        * timing
    )
