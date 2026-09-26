"""Two weekly refreshes through the real pipeline, loaders, scoring and HTTP API.

Adapters are faked (canonical frames, no network) so the scenario is exact:
week 1 is the baseline; week 2 brings a new owner, a new EV permit and a new home.
"""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import func, select, text

from app.db import SessionLocal
from app.leads import pipeline
from app.leads.config import scoring
from app.leads.frames import METER_COLUMNS, PARCEL_COLUMNS, PERMIT_COLUMNS, PROPERTY_COLUMNS
from app.leads.scoring import score_leads
from app.models import Property

NOW = datetime.now(UTC).replace(microsecond=0)
WEEK1 = NOW - timedelta(days=8)
WEEK2 = NOW


def home(account, address, zip_code, **kw):
    row = {
        "county": "harris",
        "account": account,
        "situs_address": address,
        "situs_city": "HOUSTON",
        "situs_zip": zip_code,
        "owner_name": "DOE JANE",
        "mail_address": "1 FAKE ST HOUSTON TX 77000",
        "state_class": "A1",
        "is_single_family": True,
        "homestead": True,
        "confidential": False,
        "market_value": 300_000.0,
        "heated_sqft": 2_000.0,
        "year_built": 1990,
        "has_solar": False,
        "has_pool": False,
    }
    return row | kw


def meter(esiid, address, zip_code, published, **kw):
    row = {
        "esiid": esiid,
        "tdsp": "centerpoint",
        "address": address,
        "city": "HOUSTON",
        "zip": zip_code,
        "county": "harris",
        "premise_type": "residential",
        "status": "active",
        "published_at": published,
    }
    return row | kw


def permit(permit_id, address, zip_code, category, issued):
    return {
        "source": "harris_permits",
        "permit_id": permit_id,
        "address": address,
        "city": "HOUSTON",
        "zip": zip_code,
        "issued_date": issued.date(),
        "category": category,
        "description": category,
        "lat": None,
        "lon": None,
    }


WEEK1_HOMES = [
    # Eligible, big and valuable, with solar. Address spelled differently in every source.
    home("A", "1200 North Oak Street", "77002", heated_sqft=4_000.0, market_value=900_000.0),
    # Eligible, small.
    home("B", "15 Elm Dr", "77003", heated_sqft=1_500.0, market_value=200_000.0),
    home("C", "20 Pine Ln", "77003", homestead=False),  # rented out
    home("D", "30 Cedar Ct", "77004", confidential=True, owner_name=None),
    home("E", "40 Birch Rd", "77005"),  # meter on a TDSP Base doesn't serve
    home("F", "50 Maple Ave", "77005"),  # commercial meter
    home("H", "60 Walnut Way", "77006"),  # no meter at all
]
WEEK1_METERS = [
    meter("1001", "1200 N OAK ST", "77002-1234", WEEK1),
    meter("1002", "15 ELM DRIVE", "77003", WEEK1),
    meter("1003", "20 PINE LN", "77003", WEEK1),
    meter("1004", "30 CEDAR CT", "77004", WEEK1),
    meter("1005", "40 BIRCH RD", "77005", WEEK1, tdsp="sharyland"),
    meter("1006", "50 MAPLE AVE", "77005", WEEK1, premise_type="small_non_residential"),
]
WEEK1_PERMITS = [permit("P1", "1200 N. Oak St.", "77002", "solar", WEEK1 - timedelta(days=30))]

WEEK2_HOMES = [
    *[h | {"owner_name": "SMITH ALEX"} if h["account"] == "B" else h for h in WEEK1_HOMES],
    home("G", "70 Aspen Cove", "77007", year_built=NOW.year),
]
WEEK2_METERS = [*WEEK1_METERS, meter("1007", "70 ASPEN CV", "77007", WEEK2)]
WEEK2_PERMITS = [
    *WEEK1_PERMITS,
    permit("P2", "1200 NORTH OAK STREET", "77002", "ev_charger", WEEK2 - timedelta(days=2)),
]


def fake(rows, columns, version):
    frame = pd.DataFrame(rows, columns=columns)
    return SimpleNamespace(
        fingerprint=lambda: version, fetch=lambda raw_dir: [], parse=lambda paths: frame
    )


def refresh(homes, meters, permits, version, now):
    runs = {
        "hcad": pipeline.run_source("hcad", now=now, module=fake(homes, PROPERTY_COLUMNS, version)),
        "ercot_esiid": pipeline.run_source(
            "ercot_esiid", now=now, module=fake(meters, METER_COLUMNS, version)
        ),
        "harris_permits": pipeline.run_source(
            "harris_permits", now=now, module=fake(permits, PERMIT_COLUMNS, version)
        ),
    }
    return runs, score_leads(now, scoring)


@pytest.fixture(autouse=True)
def raw_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "RAW_DIR", tmp_path)


def by_account(client, account):
    with SessionLocal() as db:
        prop_id = db.scalar(select(Property.id).where(Property.account == account))
    return client.get(f"/leads/{prop_id}")


def test_two_weekly_refreshes(client):
    runs, summary = refresh(WEEK1_HOMES, WEEK1_METERS, WEEK1_PERMITS, "v1", WEEK1)
    assert {r.status for r in runs.values()} == {"success"}
    assert runs["hcad"].inserted == 7
    # Only A and B pass every eligibility rule (C-H each fail exactly one).
    assert summary == {"candidates": 5, "eligible": 2, "new": 0}

    page = client.get("/leads").json()
    assert page["total"] == 2
    a, b = page["items"]
    assert a["address"] == "1200 North Oak Street" and a["signals"] == ["solar"]
    assert a["score"] > b["score"]
    # The baseline load announces nothing as "new".
    assert a["triggered_at"] is None and b["triggered_at"] is None

    runs, summary = refresh(WEEK2_HOMES, WEEK2_METERS, WEEK2_PERMITS, "v2", WEEK2)
    assert runs["hcad"].inserted == 1 and runs["hcad"].updated == 7
    assert summary == {"candidates": 6, "eligible": 3, "new": 3}

    triggers = {i["address"]: i["trigger"] for i in client.get("/leads").json()["items"]}
    assert triggers == {
        "1200 North Oak Street": "New EV charger permit",
        "15 Elm Dr": "New owner",
        "70 Aspen Cove": "New electric meter",
    }
    summary = client.get("/leads/summary").json()
    assert summary["properties"] == 8 and summary["leads"] == 3
    assert summary["new_this_week"] == 3
    assert summary["by_signal"]["solar"] == 1 and summary["by_signal"]["new_owner"] == 1

    detail = by_account(client, "A").json()
    assert "owner_name" not in detail and "mail_address" not in detail
    assert sum(d["weight"] for d in detail["drivers"]) == pytest.approx(1)
    assert {e["type"] for e in detail["evidence"]} == {"solar", "ev_charger"}
    drivers = {d["key"]: d for d in detail["drivers"]}
    assert drivers["home_size"]["value"] == 4_000 and drivers["solar"]["score"] == 100


def test_lead_filters_and_review_status(client):
    refresh(WEEK1_HOMES, WEEK1_METERS, WEEK1_PERMITS, "v1", WEEK1)
    refresh(WEEK2_HOMES, WEEK2_METERS, WEEK2_PERMITS, "v2", WEEK2)

    def addresses(**params):
        return [i["address"] for i in client.get("/leads", params=params).json()["items"]]

    assert addresses(signals="solar") == ["1200 North Oak Street"]
    assert addresses(signals=["solar", "new_owner"]) == []
    assert addresses(zip="77003") == ["15 Elm Dr"]
    assert len(addresses(new_only=True)) == 3
    assert len(addresses(limit=1)) == 1
    assert addresses(limit=1, offset=1) == addresses()[1:2]
    assert client.get("/leads", params={"signals": "bogus"}).status_code == 422

    lead_id = by_account(client, "B").json()["id"]
    resp = client.patch(f"/leads/{lead_id}", json={"status": "qualified"})
    assert resp.status_code == 200 and resp.json()["status"] == "qualified"
    assert client.patch(f"/leads/{lead_id}", json={"status": "nope"}).status_code == 422
    assert addresses(status="qualified") == ["15 Elm Dr"]

    # Re-scoring keeps the reviewer's status and the lead's trigger.
    score_leads(WEEK2 + timedelta(hours=1), scoring)
    again = client.get(f"/leads/{lead_id}").json()
    assert again["status"] == "qualified" and again["trigger"] == "New owner"

    assert client.get("/leads/999999").status_code == 404
    assert client.patch("/leads/999999", json={"status": "new"}).status_code == 404


def test_refresh_skips_unchanged_and_guards_bad_data(client):
    homes = fake(WEEK1_HOMES, PROPERTY_COLUMNS, "v1")
    assert pipeline.run_source("hcad", now=WEEK1, module=homes).status == "success"
    # Same upstream version: nothing to do.
    assert pipeline.run_source("hcad", now=WEEK2, module=homes).status == "skipped"

    # A new version that lost most rows is refused, and the data stays as it was.
    shrunk = fake(WEEK1_HOMES[:1], PROPERTY_COLUMNS, "v2")
    run = pipeline.run_source("hcad", now=WEEK2, module=shrunk)
    assert run.status == "failed" and "quality gate" in run.error

    def broken_parse(paths):
        raise RuntimeError("upstream changed its format")

    broken = SimpleNamespace(fingerprint=lambda: "v3", fetch=lambda d: [], parse=broken_parse)
    run = pipeline.run_source("hcad", now=WEEK2, module=broken)
    assert run.status == "failed" and "upstream changed its format" in run.error

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Property)) == 7

    sources = {s["source_id"]: s for s in client.get("/sources").json()}
    assert sources["hcad"]["status"] == "failed"
    assert sources["hcad"]["last_success_at"] is not None
    assert sources["ercot_esiid"]["status"] is None  # never run


def test_baseline_rescore_announces_nothing(client):
    refresh(WEEK1_HOMES, WEEK1_METERS, WEEK1_PERMITS, "v1", WEEK1)
    # A rule/matching change makes home H eligible; that isn't news about the home.
    pipeline.run_source(
        "ercot_esiid",
        now=WEEK2,
        module=fake(
            [*WEEK1_METERS, meter("1008", "60 WALNUT WAY", "77006", WEEK1)], METER_COLUMNS, "v2"
        ),
    )
    with SessionLocal() as db:  # the meter existed all along; only our matching changed
        db.execute(text("UPDATE meters SET first_seen_at = :t"), {"t": WEEK1})
        db.commit()
    score_leads(WEEK2, scoring, baseline=True)

    page = client.get("/leads").json()
    assert page["total"] == 3
    assert all(item["trigger"] is None for item in page["items"])


def test_appraisal_solar_and_pool_signals(client):
    homes = [
        h | {"has_solar": True, "has_pool": True} if h["account"] == "B" else h for h in WEEK1_HOMES
    ]
    refresh(homes, WEEK1_METERS, [], "v1", WEEK1)
    detail = by_account(client, "B").json()
    evidence = {e["type"]: e for e in detail["evidence"]}
    assert evidence["solar"]["source"] == "appraisal" and "pool" in evidence
    drivers = {d["key"]: d["score"] for d in detail["drivers"]}
    assert drivers["solar"] == 100 and drivers["pool"] == 100
    assert [
        i["address"] for i in client.get("/leads", params={"signals": "pool"}).json()["items"]
    ] == ["15 Elm Dr"]


def test_map_points_and_cells(client, monkeypatch):
    refresh(WEEK1_HOMES, WEEK1_METERS, WEEK1_PERMITS, "v1", WEEK1)
    parcels = [
        {"county": "harris", "account": "A", "lat": 29.76, "lon": -95.37},
        {"county": "harris", "account": "B", "lat": 29.70, "lon": -95.40},
        {"county": "harris", "account": "ZZZ", "lat": 29.0, "lon": -95.0},  # no such account
    ]
    run = pipeline.run_source("hcad_parcels", now=WEEK1, module=fake(parcels, PARCEL_COLUMNS, "v1"))
    assert run.status == "success" and run.updated == 2
    assert by_account(client, "A").json()["lat"] == 29.76

    houston = {"bbox": "-95.5,29.6,-95.3,29.8", "zoom": 12}
    geo = client.get("/leads/geo", params=houston).json()
    assert geo["type"] == "FeatureCollection" and not geo["aggregated"]
    assert sorted(f["properties"]["address"] for f in geo["features"]) == [
        "1200 North Oak Street",
        "15 Elm Dr",
    ]
    point = next(f for f in geo["features"] if f["properties"]["address"] == "15 Elm Dr")
    assert point["geometry"]["coordinates"] == [-95.40, 29.70]

    # Filters apply to the map too.
    solar = client.get("/leads/geo", params=houston | {"signals": "solar"}).json()
    assert [f["properties"]["address"] for f in solar["features"]] == ["1200 North Oak Street"]
    # Outside the view: nothing.
    assert client.get("/leads/geo", params={"bbox": "-94,30,-93,31"}).json()["total"] == 0

    # Crowded views come back as grid cells with a count and average score.
    monkeypatch.setattr("app.routers.leads.MAX_MAP_POINTS", 1)
    cells = client.get("/leads/geo", params=houston | {"zoom": 4}).json()
    assert cells["aggregated"] and cells["total"] == 2
    assert sum(f["properties"]["count"] for f in cells["features"]) == 2

    assert client.get("/leads/geo", params={"bbox": "nope"}).status_code == 422


def test_value_per_battery_size_and_priority(client):
    VALUES = {25: 560, 40: 900, 50: 1120}  # last 12 months
    YEARS = {
        2024: {"25": 700, "40": 1100, "50": 1400},
        2025: {"25": 300, "40": 480, "50": 600},
    }
    with SessionLocal() as db:  # grid compute output for the Houston zone
        db.execute(
            text(
                "INSERT INTO grid_zone_metrics (settlement_point, period_start, period_end, "
                "grid_value_score, metrics, scores, series) "
                "VALUES ('LZ_HOUSTON', :t, :t, 10, :m, '{}', :s)"
            ),
            {
                "t": WEEK1,
                "m": json.dumps(
                    {f"battery_value_{k}": v for k, v in VALUES.items()}
                    | {f"battery_ceiling_{k}": 2 * v for k, v in VALUES.items()}
                ),
                "s": json.dumps(
                    {
                        "battery_years": [
                            {"year": y} | v | {f"ceiling_{k}": 2 * x for k, x in v.items()}
                            for y, v in YEARS.items()
                        ]
                    }
                ),
            },
        )
        db.commit()
    homes = [h | {"has_pool": True} if h["account"] == "B" else h for h in WEEK1_HOMES]
    refresh(homes, WEEK1_METERS, WEEK1_PERMITS, "v1", WEEK1)
    parcels = [{"county": "harris", "account": "A", "lat": 29.76, "lon": -95.37}]  # Houston
    pipeline.run_source("hcad_parcels", now=WEEK1, module=fake(parcels, PARCEL_COLUMNS, "v1"))
    score_leads(WEEK1, scoring)

    a = by_account(client, "A").json()  # point inside LZ_HOUSTON
    b = by_account(client, "B").json()  # no point: zone from its CenterPoint meter
    assert a["load_zone"] == b["load_zone"] == "LZ_HOUSTON"
    # Valued on the average full year, not the last 12 months.
    assert a["battery_values"]["50"] == {
        "value": 1000,
        "ceiling": 2000,
        "first_year": 2024,
        "last_year": 2025,
        "recent": 1120,
        "low": 600,
        "low_year": 2025,
        "high": 1400,
        "high_year": 2024,
    }
    assert {k: v["value"] for k, v in a["battery_values"].items()} == {
        "25": 500,
        "40": 790,
        "50": 1000,
    }
    assert (a["recommended_kwh"], a["value"]) == (50, 1000)  # 4,000 sqft
    assert a["sizing_reason"] == "4,000 sqft home → 50 kWh"
    assert (b["recommended_kwh"], b["value"]) == (40, 790)  # 1,500 sqft + pool
    assert a["expected_value"] == round(a["score"] / 100 * 1000)
    kinds = {d["key"]: d["kind"] for d in a["drivers"]}
    assert kinds["home_size"] == "percentile" and kinds["solar"] == "flag"

    by_priority = client.get("/leads").json()["items"]
    assert [i["expected_value"] for i in by_priority] == sorted(
        (i["expected_value"] for i in by_priority), reverse=True
    )
    by_value = client.get("/leads", params={"sort": "value"}).json()["items"]
    assert by_value[0]["value"] == 1000
