"""Live grid: ERCOT Grid Condition (official) + Grid Stress Signals (ours), at a given `now`."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from app import geo
from app.db import SessionLocal
from app.grid.store import upsert_prices
from app.models import Cell, GridPrice
from app.need.enrich import enrich_load_zones
from app.need.live.grid import grid_live, refresh_prices, take_grid_poll
from app.need.store import seed_polygon

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/ercot"
HOUSTON = (29.7604, -95.3698)
AUSTIN = (30.2672, -97.7431)
GULF = (27.0, -94.0)  # no Load Zone
H8, A8, G8 = (geo.latlng_to_cell(*p) for p in (HOUSTON, AUSTIN, GULF))
NOW = datetime(2026, 9, 26, 20, 30, tzinfo=UTC)  # 15:30 CDT


def square(lat: float, lng: float, d: float = 0.004) -> dict:
    ring = [[lng - d, lat - d], [lng + d, lat - d], [lng + d, lat + d], [lng - d, lat + d]]
    return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}


def dashboards(state="normal", title="Normal Conditions", eea=0, prc="18,957", margin=None):
    prc_json = json.loads((FIXTURES / "daily-prc.json").read_text())
    prc_json["current_condition"].update(state=state, title=title, eea_level=eea, prc_value=prc)
    sd = json.loads((FIXTURES / "supply-demand.json").read_text())
    if margin is not None:  # squeeze one forecast point to the requested margin
        point = [r for r in sd["data"] if r["forecast"]][-1]  # late tonight: still ahead
        point["demand"] = point["capacity"] - margin
    return prc_json, sd


def poll(at: datetime, **kwargs):
    def fetch():
        if "error" in kwargs:
            raise kwargs["error"]
        return dashboards(**kwargs)

    with SessionLocal() as db:
        row = take_grid_poll(db, fetch, at)
        db.commit()
    return row


def live(h3: str, at: datetime = NOW) -> dict:
    with SessionLocal() as db:
        return grid_live(db, [db.get(Cell, h3)], at)[h3]


def price(point: str, market: str, start: datetime, value: float) -> None:
    upsert_prices(
        pd.DataFrame(
            [
                {
                    "settlement_point": point,
                    "market": market,
                    "interval_start": pd.Timestamp(start),
                    "price": value,
                }
            ]
        )
    )


@pytest.fixture(autouse=True)
def cells():
    with SessionLocal() as db:
        for p in (HOUSTON, AUSTIN, GULF):
            seed_polygon(db, square(*p))
        enrich_load_zones(db)
        db.commit()


def types(result: dict) -> list[str]:
    return sorted(s["type"] for s in result["stressSignals"])


def test_normal_grid_has_no_official_signal_and_no_stress():
    poll(NOW - timedelta(minutes=2))
    result = live(H8)
    assert result["condition"]["state"] == "normal"
    assert result["condition"]["official"] is False  # Normal: nothing declared
    assert result["condition"]["stale"] is False
    assert types(result) == []


def test_declared_emergency_is_official_and_distinct_from_our_signals():
    poll(
        NOW - timedelta(minutes=2),
        state="eea2",
        title="Energy Emergency Alert Level 2",
        eea=2,
        prc="1,900",
        margin=1500,
    )
    result = live(H8)
    assert (result["condition"]["official"], result["condition"]["eeaLevel"]) == (True, 2)
    # Our own readings stay separate, and are tagged reliability.
    assert types(result) == ["low_reserves", "tight_margin"]
    assert {s["category"] for s in result["stressSignals"]} == {"reliability"}


def test_failed_poll_keeps_the_last_condition_then_goes_stale():
    poll(NOW - timedelta(minutes=10), prc="2,400")
    poll(NOW - timedelta(minutes=5), error=RuntimeError("HTTP 503"))
    result = live(H8)
    assert result["condition"]["prcMw"] == 2400 and result["condition"]["stale"] is False
    assert types(result) == ["low_reserves"]
    later = live(H8, NOW + timedelta(minutes=11))  # 21 min since the last success
    assert later["condition"]["stale"] is True


def test_realtime_spike_only_in_the_cells_zone_and_only_while_recent():
    poll(NOW - timedelta(minutes=2))
    price("LZ_HOUSTON", "RT", NOW - timedelta(minutes=15), 1500.0)
    price("LZ_AEN", "RT", NOW - timedelta(minutes=15), 45.0)
    houston, austin = live(H8), live(A8)
    [spike] = houston["stressSignals"]
    assert (spike["type"], spike["category"], spike["value"]) == (
        "rt_price_spike",
        "market",
        1500.0,
    )
    assert houston["prices"]["loadZone"] == "LZ_HOUSTON"
    assert houston["prices"]["latestRt"]["price"] == 1500.0
    assert types(austin) == []
    assert types(live(H8, NOW + timedelta(minutes=45))) == []  # price now 60 min old
    assert live(H8, NOW + timedelta(minutes=45))["prices"]["stale"] is True


def test_day_ahead_spike_in_the_upcoming_hours_of_the_cells_zone():
    poll(NOW - timedelta(minutes=2))
    tomorrow_5pm = datetime(2026, 9, 27, 22, 0, tzinfo=UTC)  # 17:00 CDT
    for h in range(3):
        price("LZ_HOUSTON", "DA", tomorrow_5pm + timedelta(hours=h), 1200.0 + h)
    [spike] = live(H8)["stressSignals"]
    assert spike["type"] == "dam_price_spike"
    assert spike["value"] == 1202.0  # peak
    assert spike["at"] == tomorrow_5pm  # first hour at or above the threshold
    assert spike["hours"] == 3
    assert "3 hours" in spike["message"]
    assert types(live(A8)) == []


def test_cell_without_a_zone_gets_statewide_signals_only():
    poll(NOW - timedelta(minutes=2), prc="2,000")
    price("LZ_HOUSTON", "RT", NOW - timedelta(minutes=15), 1500.0)
    result = live(G8)
    assert types(result) == ["low_reserves"]
    assert result["prices"]["loadZone"] is None
    assert result["notes"] == ["No Load Zone for this Cell: price signals unavailable"]


def test_api_shape_keeps_official_and_derived_apart(client):
    now = datetime.now(UTC)
    poll(now - timedelta(minutes=1), prc="2,000")
    grid = client.get(f"/need/cells/{H8}").json()["live"]["grid"]
    assert set(grid) == {"condition", "prices", "stressSignals", "notes"}
    assert grid["condition"]["official"] is False
    assert [s["type"] for s in grid["stressSignals"]] == ["low_reserves"]
    body = client.get("/need/cells", params={"bbox": "-98.1,29.6,-95.2,30.5"}).json()
    props = {f["id"]: f["properties"] for f in body["features"]}
    assert (props[H8]["gridState"], props[H8]["activeGridStressSignals"]) == ("normal", 1)


def test_thresholds_are_strict_and_stale_conditions_give_no_signals():
    poll(NOW - timedelta(minutes=2), prc="3,000", margin=3000)
    assert types(live(H8)) == []  # exactly at our thresholds: not below
    poll(NOW - timedelta(minutes=1), prc="1,000")
    assert types(live(H8)) == ["low_reserves"]
    # 25 min later with no new poll: the reading is stale, so it is not a live signal.
    stale = live(H8, NOW + timedelta(minutes=25))
    assert stale["condition"]["stale"] is True
    assert types(stale) == []


def test_todays_remaining_day_ahead_hours_count_too():
    poll(NOW - timedelta(minutes=2))
    tonight = datetime(2026, 9, 27, 0, 0, tzinfo=UTC)  # 19:00 CDT today
    price("LZ_HOUSTON", "DA", tonight, 1500.0)
    price("LZ_HOUSTON", "DA", NOW - timedelta(hours=2), 3000.0)  # already past: ignored
    [spike] = live(H8)["stressSignals"]
    assert (spike["type"], spike["value"], spike["hours"]) == ("dam_price_spike", 1500.0, 1)


def test_refreshing_prices_twice_is_idempotent():
    frame = pd.DataFrame(
        [
            {
                "settlement_point": "LZ_HOUSTON",
                "market": "RT",
                "interval_start": pd.Timestamp(NOW),
                "price": 40.0,
            }
        ]
    )
    refresh_prices("RT", lambda market, documents: frame)
    refresh_prices("RT", lambda market, documents: frame.assign(price=41.0))
    with SessionLocal() as db:
        rows = db.query(GridPrice).filter(GridPrice.settlement_point == "LZ_HOUSTON").all()
    assert [(r.price) for r in rows] == [41.0]  # one row, latest value


def test_map_response_carries_the_statewide_condition_once(client):
    poll(datetime.now(UTC) - timedelta(minutes=1), state="eea1", title="EEA Level 1", eea=1)
    body = client.get("/need/cells", params={"bbox": "-80,20,-79,21"}).json()  # no Cells here
    assert body["features"] == []
    assert body["grid"] == {
        "state": "eea1",
        "title": "EEA Level 1",
        "eeaLevel": 1,
        "official": True,
        "stale": False,
    }
