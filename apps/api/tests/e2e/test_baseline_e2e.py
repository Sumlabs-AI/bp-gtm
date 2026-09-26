"""Baseline Need end to end: statewide res-6 reference and Cells built from the same inputs."""

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from app import geo
from app.db import SessionLocal
from app.models import BaselineNeedReference, CellBaselineNeed
from app.need.baseline import compute_baseline
from app.need.enrich import enrich_counties, enrich_load_zones
from app.need.outage.store import save_county_features, save_utility_reliability
from app.need.store import seed_polygon
from app.need.weather.store import save_county_temperature, save_storm_features

HOUSTON = (29.7604, -95.3698)
AUSTIN = (30.2672, -97.7431)
H8, A8 = geo.latlng_to_cell(*HOUSTON), geo.latlng_to_cell(*AUSTIN)
H6, A6 = geo.cell_to_parent(H8, 6), geo.cell_to_parent(A8, 6)
FAR = [geo.latlng_to_cell(32.0 + i * 0.3, -101.0, 6) for i in range(3)]  # reference-only


def square(lat: float, lng: float, d: float = 0.004) -> dict:
    ring = [[lng - d, lat - d], [lng + d, lat - d], [lng + d, lat + d], [lng - d, lat + d]]
    return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}


def county(fips: str, exposure: float | None) -> dict:
    return {
        "county_fips": fips,
        "county_name": fips,
        "modeled_customers": 1,
        "data_through": date(2025, 12, 31),
        "years_observed": 5,
        "in_reference": exposure is not None,
        "hours_per_customer_365d": 1.0,
        "outage_events_365d": 1,
        "major_outage_events_365d": 0,
        "peak_pct_out_365d": 0.1,
        "hours_per_customer_5y": 1.0,
        "outage_events_5y": 1,
        "major_outage_events_5y": 0,
        "peak_pct_out_5y": 0.1,
        "last_observed_major_outage_on": None,
        "hours_per_customer_pctl": exposure,
        "observed_exposure": exposure,
    }


def storm(h6: str, exposure: float) -> dict:
    return {
        "h3_index": h6,
        "resolution": 6,
        "data_through": date(2026, 9, 25),
        "issuing_office": "HGX",
        "warning_days_5y": 1,
        "warning_days_365d": 1,
        "severe_thunderstorm_warnings_5y": 1,
        "tornado_warnings_5y": 0,
        "extreme_wind_warnings_5y": 0,
        "storm_exposure": exposure,
    }


def temperature(fips: str, exposure: float) -> dict:
    return {
        "county_fips": fips,
        "county_name": fips,
        "data_through": date(2026, 2, 28),
        "heat_days_100f_5y": 1,
        "heat_days_95f_5y": 1,
        "cold_days_28f_5y": 1,
        "cold_days_32f_5y": 1,
        "heat_days_100f_365d": 1,
        "heat_days_95f_365d": 1,
        "cold_days_28f_365d": 1,
        "cold_days_32f_365d": 1,
        "heat_100f_pctl": exposure,
        "cold_28f_pctl": exposure,
        "temperature_exposure": exposure,
    }


# Reference res-6 cells -> county (injected: no Census download in tests).
COUNTY_OF = {H6: "48201", A6: "48453", FAR[0]: "48303", FAR[1]: "48303", FAR[2]: "48111"}


@pytest.fixture
def world():
    with SessionLocal() as db:
        for p in (HOUSTON, AUSTIN):
            seed_polygon(db, square(*p))
        enrich_load_zones(db)
        enrich_counties(db)
        now = datetime.now(UTC)
        save_county_features(
            db,
            pd.DataFrame(
                [
                    county("48201", 76.0),
                    county("48453", 52.0),
                    county("48303", 10.0),
                    county("48111", None),
                ]
            ),
            now,
        )
        save_utility_reliability(
            db,
            pd.DataFrame(
                [
                    {
                        "utility_id": 8901,
                        "utility_name": "CenterPoint Energy",
                        "ownership": "x",
                        "customers": 1.0,
                        "data_through_year": 2024,
                        "years_used": 5,
                        "saidi_wo_med_5y": 150.0,
                        "saifi_wo_med_5y": 1.0,
                        "saidi_w_med_5y": 1500.0,
                        "saifi_w_med_5y": 2.0,
                        "reliability_need": 46.0,
                        "yearly": {},
                    }
                ]
            ),
            now,
        )
        save_storm_features(
            db,
            pd.DataFrame([storm(H6, 54.0), storm(A6, 34.0)] + [storm(f, 90.0) for f in FAR]),
            now,
        )
        save_county_temperature(
            db,
            pd.DataFrame(
                [
                    temperature("48201", 8.0),
                    temperature("48453", 47.0),
                    temperature("48303", 80.0),
                    temperature("48111", 60.0),
                ]
            ),
            now,
        )
        report = compute_baseline(db, county_of=lambda cells: {h: COUNTY_OF[h] for h in cells})
        db.commit()
    return report


def test_reference_and_cells_use_the_same_inputs(world):
    assert world.reference_cells == 5  # every res-6 cell with Storm features
    with SessionLocal() as db:
        ref = {r.h3_index: r for r in db.query(BaselineNeedReference)}
        cell = db.get(CellBaselineNeed, H8)
    # Houston Cell and its res-6 parent: same county, same storm -> identical inputs and raw.
    assert (cell.outage_input, cell.weather_input, cell.raw) == (
        ref[H6].outage_input,
        ref[H6].weather_input,
        ref[H6].raw,
    )
    assert cell.outage_input == 76.0  # Observed Outage Exposure, not the utility-blended 61
    assert cell.weather_input == pytest.approx((54.0 + 8.0) / 2)
    # County outside the outage Reference Population: weather alone.
    assert ref[FAR[2]].outage_input is None and ref[FAR[2]].raw == pytest.approx(75.0)


def test_baseline_need_is_a_percentile_of_the_reference(world):
    with SessionLocal() as db:
        raws = sorted(r.raw for r in db.query(BaselineNeedReference))
        houston = db.get(CellBaselineNeed, H8)
    below = sum(r < houston.raw for r in raws)
    ties = sum(r == houston.raw for r in raws)
    assert houston.baseline_need == pytest.approx((below + ties / 2) / len(raws) * 100)
    assert houston.dominant_driver == "outage"


def test_api_exposes_baseline_without_touching_need_score(client, world):
    cell = client.get(f"/need/cells/{H8}").json()
    assert cell["needScore"] is None
    b = cell["baseline"]
    assert b["dominantDriver"] == "outage"
    assert b["inputs"] == {"observedOutageExposure": 76.0, "weatherNeed": pytest.approx(31.0)}
    assert b["context"] == {"utilityReliabilityNeed": 46.0}  # context, not an input
    assert b["raw"] == pytest.approx(83.44, abs=0.01)
    assert "union" in b["method"]
    assert any("humidity" in lim for lim in b["limitations"])
    body = client.get("/need/cells", params={"bbox": "-98.1,29.6,-95.2,30.5"}).json()
    props = {f["id"]: f["properties"] for f in body["features"]}
    assert props[H8]["baselineNeed"] == b["baselineNeed"]
    assert props[A8]["baselineNeed"] is not None
