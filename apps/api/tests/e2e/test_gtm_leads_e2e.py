"""GTM page back end: leads ranked by their Cell, filtered by Cells, bands and live signals."""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import select, update

from app import geo
from app.db import SessionLocal
from app.leads.store import assign_cells, load_locations
from app.models import CellBaselineNeed, Lead, Property
from app.need.enrich import enrich_counties, enrich_load_zones
from app.need.live.alerts import take_snapshot
from app.need.store import seed_polygon

NOW = datetime.now(UTC).replace(microsecond=0)
# Three Houston-area spots, each its own res-8 Cell, plus a spot outside every Cell.
A = (29.7604, -95.3698)  # downtown
B = (29.9500, -95.6500)  # NW Houston
C = (29.6000, -95.1000)  # SE
OUT = (27.0000, -94.0000)  # Gulf: no Cell
CELL = {k: geo.latlng_to_cell(*p) for k, p in {"A": A, "B": B, "C": C}.items()}


def square(lat: float, lng: float, d: float = 0.004) -> dict:
    ring = [[lng - d, lat - d], [lng + d, lat - d], [lng + d, lat + d], [lng - d, lat + d]]
    return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}


def add_home(db, account: str, spot: tuple[float, float], kwh: float, value: float) -> int:
    prop = Property(
        county="harris",
        account=account,
        situs_address=f"{account} TEST ST",
        situs_city="HOUSTON",
        situs_zip="77002",
        address_key=f"{account} TEST ST 77002",
        state_class="A1",
        is_single_family=True,
        homestead=True,
        confidential=False,
        market_value=300_000.0,
        heated_sqft=2_000.0,
        year_built=1990,
        lat=spot[0],
        lon=spot[1],
        h3_index=geo.latlng_to_cell(*spot),
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    db.add(prop)
    db.flush()
    db.add(
        Lead(
            property_id=prop.id,
            score=50.0,
            drivers={},
            signals=[],
            reasons="",
            first_seen_at=NOW,
            status="new",
            load_zone="LZ_HOUSTON",
            value=value,
            expected_value=value / 2,
            annual_kwh=kwh,
            scored_at=NOW,
        )
    )
    return prop.id


def baseline(db, h3: str, need: float | None) -> None:
    db.add(
        CellBaselineNeed(
            h3_index=h3,
            outage_input=need,
            weather_input=need,
            raw=need,
            baseline_need=need,
            dominant_driver="outage",
            notes=[],
            computed_at=NOW,
        )
    )


@pytest.fixture
def world():
    """Cells A (need 80), B (need 60, on a band edge), C (need 30); homes in each, one outside."""
    with SessionLocal() as db:
        for spot in (A, B, C):
            seed_polygon(db, square(*spot))
        enrich_load_zones(db)
        enrich_counties(db)
        baseline(db, CELL["A"], 80.0)
        baseline(db, CELL["B"], 60.0)
        baseline(db, CELL["C"], 30.0)
        ids = {
            "a_small": add_home(db, "A1", A, kwh=9_000, value=900),
            "a_big": add_home(db, "A2", A, kwh=26_000, value=500),
            "b": add_home(db, "B1", B, kwh=15_000, value=1_200),
            "c": add_home(db, "C1", C, kwh=30_000, value=2_000),
            "out": add_home(db, "O1", OUT, kwh=40_000, value=3_000),
        }
        db.commit()
    return ids


def ids(client, **params) -> list[int]:
    r = client.get("/leads", params=params)
    assert r.status_code == 200, r.text
    return [i["id"] for i in r.json()["items"]]


def test_default_ranking_is_cell_need_then_home_consumption(client, world):
    # Need 80 first (big home before small), then 60, then 30; the Cell-less home last.
    assert ids(client) == [world["a_big"], world["a_small"], world["b"], world["c"], world["out"]]
    # Expected Value would have ordered them the other way round: still available as a sort.
    assert ids(client, sort="priority")[0] == world["out"]


def test_each_lead_carries_its_cells_scores_read_at_request_time(client, world):
    items = {i["id"]: i for i in client.get("/leads").json()["items"]}
    big = items[world["a_big"]]
    assert big["h3_index"] == CELL["A"]
    assert big["cell"]["baseline_need"] == 80.0
    assert big["cell"]["propensity_score"] is None
    assert (big["cell"]["active_alerts"], big["cell"]["forecast_level"]) == (0, None)
    assert items[world["out"]]["cell"] is None  # outside every Cell
    with SessionLocal() as db:  # not copied: a re-computed Cell shows up immediately
        db.execute(
            update(CellBaselineNeed)
            .where(CellBaselineNeed.h3_index == CELL["A"])
            .values(baseline_need=85.0)
        )
        db.commit()
    assert client.get("/leads").json()["items"][0]["cell"]["baseline_need"] == 85.0


def test_filter_by_cells(client, world):
    assert ids(client, cells=[CELL["B"], CELL["C"]]) == [world["b"], world["c"]]
    assert ids(client, cells=[CELL["A"]]) == [world["a_big"], world["a_small"]]


def test_filter_by_need_band_includes_the_lower_edge(client, world):
    assert ids(client, need_band=["60-80"]) == [world["b"]]  # 60 belongs to 60–80
    assert ids(client, need_band=["80-100"]) == [world["a_big"], world["a_small"]]
    assert ids(client, need_band=["0-40", "80-100"]) == [
        world["a_big"],
        world["a_small"],
        world["c"],
    ]
    assert client.get("/leads", params={"need_band": "50-70"}).status_code == 422
    # Any Cell filter excludes leads outside every Cell.
    assert world["out"] not in ids(client, need_band=["0-40", "40-60", "60-80", "80-100"])


def alert_over(spot: tuple[float, float], start: datetime, end: datetime) -> dict:
    lat, lng = spot
    return {
        "type": "FeatureCollection",
        "updated": start.isoformat(),
        "features": [
            {
                "type": "Feature",
                "id": "x",
                "geometry": square(lat, lng, 0.02),
                "properties": {
                    "id": "tor-gtm",
                    "event": "Tornado Warning",
                    "severity": "Extreme",
                    "certainty": "Observed",
                    "urgency": "Immediate",
                    "messageType": "Alert",
                    "headline": "Tornado Warning",
                    "senderName": "NWS",
                    "sent": start.isoformat(),
                    "effective": start.isoformat(),
                    "onset": start.isoformat(),
                    "expires": end.isoformat(),
                    "ends": end.isoformat(),
                    "affectedZones": [],
                    "geocode": {"UGC": []},
                },
            }
        ],
    }


def test_filter_by_active_alert_follows_the_clock(client, world, monkeypatch):
    end = NOW + timedelta(minutes=40)
    with SessionLocal() as db:
        take_snapshot(
            db,
            fetch=lambda: alert_over(B, NOW - timedelta(minutes=5), end),
            resolve_zones=lambda urls: [],
            now=NOW - timedelta(minutes=1),
        )
        db.commit()
    assert ids(client, alert="true") == [world["b"]]
    body = client.get("/leads", params={"alert": "true"}).json()
    assert body["items"][0]["cell"]["active_alerts"] == 1
    assert body["summary"]["alert"] == 1

    import app.routers.leads as leads_router

    monkeypatch.setattr(leads_router, "_now", lambda: end + timedelta(minutes=1))
    assert ids(client, alert="true") == []  # expired: nothing to call about


def test_summary_describes_the_filtered_set(client, world):
    s = client.get("/leads", params={"cells": [CELL["A"], CELL["C"]]}).json()["summary"]
    assert s["leads"] == 3
    assert s["avg_baseline_need"] == pytest.approx((80 + 80 + 30) / 3, abs=0.1)
    assert (s["alert"], s["forecast"], s["grid_stress"]) == (0, 0, 0)
    assert s["grid_state"] is None  # no ERCOT poll in the test database


def test_geo_points_respect_the_cell_filters(client, world):
    body = client.get(
        "/leads/geo", params={"bbox": "-96,29,-93,31", "zoom": 12, "cells": CELL["C"]}
    ).json()
    assert [f["properties"]["id"] for f in body["features"]] == [world["c"]]


def test_loader_sets_h3_and_backfill_is_idempotent(world):
    with SessionLocal() as db:
        db.execute(update(Property).values(h3_index=None))
        db.commit()
        assert db.scalar(select(Property.h3_index).where(Property.account == "A1")) is None
    parcels = pd.DataFrame([{"county": "harris", "account": "A1", "lat": A[0], "lon": A[1]}])
    load_locations(parcels, NOW)  # lat/lon unchanged, but h3 was missing: it's set
    with SessionLocal() as db:
        assert db.scalar(select(Property.h3_index).where(Property.account == "A1")) == CELL["A"]
    assert assign_cells() == 4  # the other located homes
    assert assign_cells() == 0
    with SessionLocal() as db:
        assert db.scalar(
            select(Property.h3_index).where(Property.account == "O1")
        ) == geo.latlng_to_cell(*OUT)
