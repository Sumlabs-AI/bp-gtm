"""Weather Need Component end to end: res-6 storm + county temperature -> Cells -> HTTP."""

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from app import geo
from app.db import SessionLocal
from app.need.enrich import enrich_counties, enrich_load_zones
from app.need.store import seed_polygon
from app.need.weather.store import save_county_temperature, save_storm_exposure

HOUSTON = (29.7604, -95.3698)
AUSTIN = (30.2672, -97.7431)


def square(lat: float, lng: float, d: float = 0.004) -> dict:
    ring = [[lng - d, lat - d], [lng + d, lat - d], [lng + d, lat + d], [lng - d, lat + d]]
    return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}


def storm(h3_6: str, exposure: float | None) -> dict:
    return {
        "h3_index": h3_6,
        "resolution": 6,
        "data_through": date(2026, 9, 25),
        "warning_days_5y": 97,
        "warning_days_365d": 18,
        "severe_thunderstorm_warnings_5y": 240,
        "tornado_warnings_5y": 41,
        "extreme_wind_warnings_5y": 1,
        "storm_exposure": exposure,
    }


def temperature(fips: str, exposure: float) -> dict:
    return {
        "county_fips": fips,
        "data_through": date(2026, 9, 22),
        "heat_days_100f_5y": 37,
        "heat_days_95f_5y": 261,
        "cold_days_28f_5y": 55,
        "cold_days_32f_5y": 69,
        "heat_days_100f_365d": 3,
        "heat_days_95f_365d": 50,
        "cold_days_28f_365d": 4,
        "cold_days_32f_365d": 9,
        "heat_100f_pctl": exposure,
        "cold_28f_pctl": exposure,
        "temperature_exposure": exposure,
    }


def seed(storms: list[dict], temps: list[dict]) -> None:
    with SessionLocal() as db:
        for lat, lng in (HOUSTON, AUSTIN):
            seed_polygon(db, square(lat, lng))
        enrich_load_zones(db)
        enrich_counties(db)
        now = datetime.now(UTC)
        save_storm_exposure(db, pd.DataFrame(storms), now)
        save_county_temperature(db, pd.DataFrame(temps), now)
        db.commit()


def weather(client, lat: float, lng: float) -> dict:
    return client.get(f"/need/cells/{geo.latlng_to_cell(lat, lng)}").json()["components"]["weather"]


@pytest.fixture
def houston_parent():
    return geo.cell_to_parent(geo.latlng_to_cell(*HOUSTON), 6)


def test_weather_combines_res6_storm_and_county_temperature(client, houston_parent):
    seed([storm(houston_parent, 80.0)], [temperature("48201", 30.0)])
    component = weather(client, *HOUSTON)
    assert component["score"] == 55.0

    storms = component["stormExposure"]
    assert storms["score"] == 80.0
    # Provenance: the value belongs to the ~36 km² res-6 parent, not the res-8 Cell.
    assert storms["resolution"] == 6
    assert storms["sourceCell"] == houston_parent
    assert storms["dataThrough"] == "2026-09-25"
    assert storms["metrics"]["warningDays5y"] == 97
    assert storms["metrics"]["tornadoWarnings5y"] == 41

    temps = component["temperatureExtremesExposure"]
    assert temps["score"] == 30.0
    assert temps["county"] == {"fips": "48201"}
    assert temps["metrics"]["heatDays100F5y"] == 37
    assert temps["metrics"]["heatDays95F5y"] == 261
    assert temps["percentiles"] == {"heatDays100F5y": 30.0, "coldDays28F5y": 30.0}
    assert temps["limitations"] == ["Dry-bulb temperature only: no humidity or heat index."]
    assert component["notes"] == []


def test_missing_storm_cell_falls_back_to_temperature(client):
    seed([], [temperature("48453", 60.0)])
    component = weather(client, *AUSTIN)
    assert component["score"] == 60.0
    assert component["stormExposure"] is None
    assert component["notes"] == [
        "No Storm Exposure for this area: score uses Temperature Extremes Exposure only"
    ]


def test_map_features_carry_weather_need(client, houston_parent):
    seed([storm(houston_parent, 80.0)], [temperature("48201", 30.0), temperature("48453", 60.0)])
    body = client.get("/need/cells", params={"bbox": "-98.1,29.6,-95.2,30.5"}).json()
    by_cell = {f["id"]: f["properties"]["weatherNeed"] for f in body["features"]}
    assert by_cell[geo.latlng_to_cell(*HOUSTON)] == 55.0
    assert by_cell[geo.latlng_to_cell(*AUSTIN)] == 60.0
