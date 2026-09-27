"""Timing from stored NWS Alert history: cell detail, map features and the /need/feed."""

from datetime import UTC, datetime, timedelta

import pytest

from app import geo
from app.db import SessionLocal
from app.models import CellBaselineNeed, CellPropensity, NwsAlert, PropensityImport
from app.need.config import timing as config
from app.need.opportunity import opportunity_score
from app.need.store import seed_polygon

HOUSTON = (29.7604, -95.3698)
AUSTIN = (30.2672, -97.7431)
H8 = geo.latlng_to_cell(*HOUSTON)
A8 = geo.latlng_to_cell(*AUSTIN)
NOW = datetime.now(UTC)


def square(lat: float, lng: float, d: float) -> dict:
    ring = [[lng - d, lat - d], [lng + d, lat - d], [lng + d, lat + d], [lng - d, lat + d]]
    return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}


def wkt(lat: float, lng: float, d: float) -> str:
    ring = ", ".join(f"{x} {y}" for x, y in square(lat, lng, d)["coordinates"][0])
    return f"SRID=4326;MULTIPOLYGON((({ring})))"


def alert(aid: str, event: str, ends: datetime, *, superseded: datetime | None = None):
    return NwsAlert(
        id=aid,
        event=event,
        category="severe_storm",
        zones=[],
        effective_at=ends - timedelta(hours=3),
        expires_at=ends,
        ends_at=ends,
        geometry=wkt(*HOUSTON, 0.05),
        geometry_source="alert",
        first_seen_at=ends - timedelta(hours=3),
        last_seen_at=ends,
        superseded_at=superseded,
    )


@pytest.fixture
def world():
    """Houston and Austin Cells with the same Opportunity; a storm only over Houston."""
    with SessionLocal() as db:
        seed_polygon(db, square(*HOUSTON, 0.004))
        seed_polygon(db, square(*AUSTIN, 0.004))
        batch = PropensityImport(
            imported_at=NOW,
            file_name="test.parquet",
            rows=2,
            product_cells=2,
            other_cells=0,
            model_versions=["v1"],
            feature_versions=["1.0.0"],
            warnings=[],
        )
        db.add(batch)
        db.flush()
        for h3 in (H8, A8):
            db.add(
                CellBaselineNeed(
                    h3_index=h3,
                    outage_input=60.0,
                    weather_input=60.0,
                    raw=60.0,
                    baseline_need=60.0,
                    dominant_driver="outage",
                    notes=[],
                    computed_at=NOW,
                )
            )
            db.add(
                CellPropensity(
                    h3_index=h3,
                    propensity_score=80.0,
                    model_version="v1",
                    feature_version="1.0.0",
                    scored_at=NOW,
                    imported_at=NOW,
                    import_id=batch.id,
                )
            )
        db.commit()


def add(*alerts: NwsAlert) -> None:
    with SessionLocal() as db:
        db.add_all(alerts)
        db.commit()


def test_storm_puts_cell_in_its_post_event_window(client, world):
    # Ended 5 days ago; NWS dropped it from the feed when it ended (superseded).
    ends = NOW - timedelta(days=5)
    add(alert("tor-1", "Tornado Warning", ends, superseded=ends + timedelta(minutes=5)))

    detail = client.get(f"/need/cells/{H8}").json()
    base = opportunity_score(80.0, 60.0)
    assert detail["opportunity"]["baseScore"] == base
    assert detail["opportunity"]["timing"] == config.peak
    assert detail["opportunity"]["score"] == opportunity_score(80.0, 60.0, config.peak)
    assert client.get(f"/need/cells/{A8}").json()["opportunity"]["score"] == base
    timing = detail["timing"]
    assert timing["phase"] == "peak"
    assert timing["multiplier"] == config.peak
    assert timing["event"] == "Tornado Warning"
    assert timing["daysSince"] == pytest.approx(5, abs=0.1)
    assert client.get(f"/need/cells/{A8}").json()["timing"]["phase"] == "none"

    lng, lat = HOUSTON[1], HOUSTON[0]
    features = client.get(
        "/need/cells", params={"bbox": f"{lng - 0.01},{lat - 0.01},{lng + 0.01},{lat + 0.01}"}
    ).json()["features"]
    props = next(f["properties"] for f in features if f["id"] == H8)
    assert (props["timingMultiplier"], props["timingPhase"]) == (config.peak, "peak")
    assert props["opportunityScore"] == opportunity_score(80.0, 60.0, config.peak)

    feed = client.get("/need/feed").json()
    assert [i["h3"] for i in feed] == [H8]  # Austin has no timing: not in this week's feed
    assert feed[0]["baseScore"] == base
    assert feed[0]["opportunityScore"] == pytest.approx(base * config.peak, abs=0.1)


def test_old_storms_and_watches_do_not_count(client, world):
    add(
        alert("tor-old", "Tornado Warning", NOW - timedelta(days=config.fade_days + 1)),
        alert("watch", "Tornado Watch", NOW - timedelta(days=2)),
    )
    assert client.get(f"/need/cells/{H8}").json()["timing"]["multiplier"] == 1.0
    assert client.get("/need/feed").json() == []


def test_cancelled_before_it_took_effect_is_ignored(client, world):
    ends = NOW - timedelta(days=3)
    # Superseded an hour before it would have taken effect: it never happened.
    add(alert("tor-x", "Tornado Warning", ends, superseded=ends - timedelta(hours=4)))
    assert client.get(f"/need/cells/{H8}").json()["timing"]["phase"] == "none"
