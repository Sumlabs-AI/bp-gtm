"""Outage Need Component end to end: county + utility features -> Cells -> HTTP API."""

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from app import geo
from app.db import SessionLocal
from app.need.enrich import enrich_counties, enrich_load_zones
from app.need.outage.store import save_county_features, save_utility_reliability
from app.need.store import seed_polygon

HOUSTON = (29.7604, -95.3698)  # Harris, CenterPoint
AUSTIN = (30.2672, -97.7431)  # Travis, Austin Energy (LZ_AEN)
LAKEWAY = (30.3632, -97.9795)  # Travis, outside Austin Energy: utility unknown
LAST_MAJOR = date(2025, 7, 8)


def square(lat: float, lng: float, d: float = 0.004) -> dict:
    ring = [[lng - d, lat - d], [lng + d, lat - d], [lng + d, lat + d], [lng - d, lat + d]]
    return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}


def county(fips: str, name: str, exposure: float | None, last_major: date | None) -> dict:
    return {
        "county_fips": fips,
        "county_name": name,
        "modeled_customers": 1_000_000,
        "data_through": date(2025, 12, 31),
        "years_observed": 5,
        "in_reference": exposure is not None,
        "hours_per_customer_365d": 2.0,
        "outage_events_365d": 12,
        "major_outage_events_365d": 1,
        "peak_pct_out_365d": 0.4,
        "hours_per_customer_5y": 30.0,
        "outage_events_5y": 70,
        "major_outage_events_5y": 6,
        "peak_pct_out_5y": 0.9,
        "last_observed_major_outage_on": last_major,
        "hours_per_customer_pctl": exposure,
        "observed_exposure": exposure,
    }


def utility(uid: int, name: str, need: float) -> dict:
    return {
        "utility_id": uid,
        "utility_name": name,
        "ownership": "x",
        "customers": 1.0,
        "data_through_year": 2024,
        "years_used": 5,
        "saidi_wo_med_5y": 150.0,
        "saifi_wo_med_5y": 1.2,
        "saidi_w_med_5y": 1500.0,
        "saifi_w_med_5y": 2.0,
        "reliability_need": need,
        "yearly": {"2024": {"saidi_wo_med": 150.0, "saidi_w_med": 1500.0}},
    }


@pytest.fixture
def cells():
    with SessionLocal() as db:
        for lat, lng in (HOUSTON, AUSTIN, LAKEWAY):
            seed_polygon(db, square(lat, lng))
        enrich_load_zones(db)
        enrich_counties(db)
        now = datetime.now(UTC)
        save_county_features(
            db,
            pd.DataFrame(
                [county("48201", "Harris", 94.0, LAST_MAJOR), county("48453", "Travis", 40.0, None)]
            ),
            now,
        )
        save_utility_reliability(
            db,
            pd.DataFrame(
                [utility(8901, "CenterPoint Energy", 74.0), utility(1015, "Austin Energy", 24.0)]
            ),
            now,
        )
        db.commit()


def outage(client, lat: float, lng: float) -> dict:
    return client.get(f"/need/cells/{geo.latlng_to_cell(lat, lng)}").json()["components"]["outage"]


def test_harris_cell_combines_county_exposure_and_centerpoint(client, cells):
    component = outage(client, *HOUSTON)
    assert component["score"] == 84.0  # mean(94, 74)
    observed = component["observedOutageExposure"]
    assert observed["score"] == 94.0
    assert observed["county"] == {"fips": "48201", "name": "Harris"}
    assert observed["dataThrough"] == "2025-12-31"
    assert observed["metrics"]["hoursPerCustomer5y"] == 30.0
    assert observed["metrics"]["majorOutageEvents5y"] == 6
    assert observed["percentiles"] == {"hoursPerCustomer5y": 94.0}  # the only scored metric
    assert observed["lastObservedMajorOutageOn"] == "2025-07-08"
    # Derived from the persisted date when read, not stored.
    assert observed["daysSinceLastObservedMajorOutage"] == (date.today() - LAST_MAJOR).days

    reliability = component["utilityReliabilityNeed"]
    assert reliability["score"] == 74.0
    assert reliability["utility"] == {"id": 8901, "name": "CenterPoint Energy"}
    assert reliability["metrics"]["saidiWithoutMed5y"] == 150.0
    assert reliability["dataThroughYear"] == 2024
    assert component["notes"] == []


def test_austin_energy_cell_uses_its_utility(client, cells):
    component = outage(client, *AUSTIN)
    assert component["utilityReliabilityNeed"]["utility"]["id"] == 1015
    assert component["score"] == 32.0  # mean(40, 24)
    assert component["observedOutageExposure"]["lastObservedMajorOutageOn"] is None
    assert component["observedOutageExposure"]["daysSinceLastObservedMajorOutage"] is None


def test_unknown_utility_falls_back_to_observed_exposure(client, cells):
    component = outage(client, *LAKEWAY)
    assert component["utilityReliabilityNeed"] is None
    assert component["score"] == 40.0
    assert component["notes"] == ["Utility unknown: score uses Observed Outage Exposure only"]


def test_map_features_carry_outage_need(client, cells):
    body = client.get("/need/cells", params={"bbox": "-98.1,29.6,-95.2,30.5"}).json()
    by_cell = {f["id"]: f["properties"]["outageNeed"] for f in body["features"]}
    assert by_cell[geo.latlng_to_cell(*HOUSTON)] == 84.0
    assert by_cell[geo.latlng_to_cell(*LAKEWAY)] == 40.0


def test_no_features_means_no_outage_component(client):
    with SessionLocal() as db:
        seed_polygon(db, square(*HOUSTON))
        enrich_counties(db)
        db.commit()
    cell = client.get(f"/need/cells/{geo.latlng_to_cell(*HOUSTON)}").json()
    assert cell["components"] == {}
    feature = client.get("/need/cells", params={"bbox": "-95.4,29.74,-95.34,29.78"}).json()[
        "features"
    ][0]
    assert feature["properties"]["outageNeed"] is None


def test_missing_county_exposure_falls_back_to_utility_reliability(client):
    # Harris outside the Reference Population (no percentile), CenterPoint ranked.
    with SessionLocal() as db:
        seed_polygon(db, square(*HOUSTON))
        enrich_load_zones(db)
        enrich_counties(db)
        now = datetime.now(UTC)
        save_county_features(db, pd.DataFrame([county("48201", "Harris", None, None)]), now)
        save_utility_reliability(db, pd.DataFrame([utility(8901, "CenterPoint Energy", 74.0)]), now)
        db.commit()
    component = outage(client, *HOUSTON)
    assert component["score"] == 74.0
    assert component["observedOutageExposure"]["score"] is None
    assert component["notes"] == [
        "County outside the Reference Population: score uses Utility Reliability Need only"
    ]


def test_known_but_unranked_utility_is_not_called_unknown(client):
    with SessionLocal() as db:
        seed_polygon(db, square(*HOUSTON))
        enrich_load_zones(db)
        enrich_counties(db)
        now = datetime.now(UTC)
        save_county_features(db, pd.DataFrame([county("48201", "Harris", 94.0, LAST_MAJOR)]), now)
        unranked = {**utility(8901, "CenterPoint Energy", 0.0), "reliability_need": None}
        save_utility_reliability(db, pd.DataFrame([unranked]), now)
        db.commit()
    component = outage(client, *HOUSTON)
    assert component["score"] == 94.0
    assert component["utilityReliabilityNeed"]["utility"]["id"] == 8901
    assert component["notes"] == [
        "Utility has no Texas reliability percentile: score uses Observed Outage Exposure only"
    ]


def test_utility_detail_includes_yearly_values_and_data_through(client, cells):
    reliability = outage(client, *HOUSTON)["utilityReliabilityNeed"]
    assert reliability["dataThrough"] == "2024-12-31"
    assert reliability["yearly"] == {"2024": {"saidiWithoutMed": 150.0, "saidiWithMed": 1500.0}}
