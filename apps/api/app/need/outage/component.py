"""The Outage Need Component of a Cell: Observed Outage Exposure (its county, EAGLE-I) and
Utility Reliability Need (its utility, EIA-861), each a Texas percentile.

Placeholder formula (equal weights, not validated): the mean of the two sub-scores, or
Observed Outage Exposure alone when the utility is unknown.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.models import Cell, CountyOutageFeatures, UtilityReliability
from app.need.config import UTILITY_BY_COUNTY, UTILITY_BY_LOAD_ZONE
from app.need.outage.store import load_features

UNKNOWN_UTILITY = "Utility unknown: score uses Observed Outage Exposure only"
UNRANKED_UTILITY = (
    "Utility has no Texas reliability percentile: score uses Observed Outage Exposure only"
)
NO_EXPOSURE = "County outside the Reference Population: score uses Utility Reliability Need only"


def utility_for(cell: Cell) -> int | None:
    """Load Zone first (Austin Energy's territory), then county."""
    return UTILITY_BY_LOAD_ZONE.get(cell.load_zone) or UTILITY_BY_COUNTY.get(cell.county_fips)


def score(exposure: float | None, reliability: float | None) -> float | None:
    """Mean of the sub-scores that exist; None when neither does."""
    present = [s for s in (exposure, reliability) if s is not None]
    return round(sum(present) / len(present), 1) if present else None


def _observed(c: CountyOutageFeatures, today: date) -> dict:
    last = c.last_observed_major_outage_on
    return {
        "score": c.observed_exposure,
        "county": {"fips": c.county_fips, "name": c.county_name},
        "source": "ORNL EAGLE-I (CC BY 4.0)",
        "dataThrough": c.data_through.isoformat(),
        "yearsObserved": c.years_observed,
        "inReferencePopulation": c.in_reference,
        "modeledCustomers": c.modeled_customers,
        "metrics": {
            "hoursPerCustomer5y": c.hours_per_customer_5y,
            "outageEvents5y": c.outage_events_5y,
            "majorOutageEvents5y": c.major_outage_events_5y,
            "peakPctOut5y": c.peak_pct_out_5y,
            "hoursPerCustomer365d": c.hours_per_customer_365d,
            "outageEvents365d": c.outage_events_365d,
            "majorOutageEvents365d": c.major_outage_events_365d,
            "peakPctOut365d": c.peak_pct_out_365d,
        },
        # Scored: only hours per customer. Events, peak and last major outage explain history.
        "percentiles": {"hoursPerCustomer5y": c.hours_per_customer_pctl},
        "lastObservedMajorOutageOn": last.isoformat() if last else None,
        # Derived when read; always shown next to dataThrough, never as live monitoring.
        "daysSinceLastObservedMajorOutage": (today - last).days if last else None,
    }


def _reliability(u: UtilityReliability) -> dict:
    return {
        "score": u.reliability_need,
        "utility": {"id": u.utility_id, "name": u.utility_name},
        "source": "EIA-861",
        "dataThrough": f"{u.data_through_year}-12-31",
        "dataThroughYear": u.data_through_year,
        "yearsUsed": u.years_used,
        "metrics": {
            "saidiWithoutMed5y": u.saidi_wo_med_5y,
            "saifiWithoutMed5y": u.saifi_wo_med_5y,
            "saidiWithMed5y": u.saidi_w_med_5y,
            "saifiWithMed5y": u.saifi_w_med_5y,
        },
        "yearly": {
            year: {"saidiWithoutMed": v["saidi_wo_med"], "saidiWithMed": v["saidi_w_med"]}
            for year, v in u.yearly.items()
        },
    }


def outage_components(db: Session, cells: list[Cell], today: date) -> dict[str, dict | None]:
    """h3_index -> Outage Need Component detail (None when the Cell's county has no
    features). One query per table, whatever the number of Cells."""
    counties, utilities = load_features(
        db,
        {c.county_fips for c in cells if c.county_fips},
        {u for c in cells if (u := utility_for(c))},
    )
    result: dict[str, dict | None] = {}
    for cell in cells:
        county = counties.get(cell.county_fips)
        utility_id = utility_for(cell)
        utility = utilities.get(utility_id)
        if county is None and utility is None:
            result[cell.h3_index] = None
            continue
        observed = _observed(county, today) if county else None
        reliability = _reliability(utility) if utility else None
        exposure = observed["score"] if observed else None
        need = reliability["score"] if reliability else None
        notes = []
        if exposure is None:
            notes.append(NO_EXPOSURE)
        if need is None:
            notes.append(UNRANKED_UTILITY if utility else UNKNOWN_UTILITY)
        result[cell.h3_index] = {
            "score": score(exposure, need),
            "observedOutageExposure": observed,
            "utilityReliabilityNeed": reliability,
            "notes": notes,
        }
    return result
