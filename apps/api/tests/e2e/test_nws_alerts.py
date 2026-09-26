"""NWS Alerts: alert Snapshots -> alerts -> Active for Cells at a given `now`."""

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app import geo
from app.db import SessionLocal
from app.models import Cell, NwsAlert
from app.need.live.alerts import take_snapshot
from app.need.live.store import active_alerts, alert_status
from app.need.store import seed_polygon

HOUSTON = (29.7604, -95.3698)
AUSTIN = (30.2672, -97.7431)
H8 = geo.latlng_to_cell(*HOUSTON)
A8 = geo.latlng_to_cell(*AUSTIN)


def t(hhmm: str) -> datetime:
    return datetime.fromisoformat(f"2026-05-16T{hhmm}:00-05:00").astimezone(UTC)


def square(lat: float, lng: float, d: float) -> dict:
    ring = [[lng - d, lat - d], [lng + d, lat - d], [lng + d, lat + d], [lng - d, lat + d]]
    return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}


def alert(
    aid: str,
    event: str,
    effective: str,
    ends: str | None,
    *,
    polygon=None,
    zones=(),
    expires: str | None = None,
) -> dict:
    return {
        "type": "Feature",
        "id": f"https://api.weather.gov/alerts/{aid}",
        "geometry": polygon,
        "properties": {
            "id": aid,
            "event": event,
            "severity": "Extreme",
            "certainty": "Observed",
            "urgency": "Immediate",
            "messageType": "Alert",
            "headline": f"{event} for test",
            "senderName": "NWS Houston/Galveston TX",
            "sent": effective,
            "effective": effective,
            "onset": effective,
            "expires": expires or ends or effective,
            "ends": ends,
            "affectedZones": [f"https://api.weather.gov/zones/forecast/{z}" for z in zones],
            "geocode": {"UGC": list(zones)},
        },
    }


def snapshot(*alerts: dict) -> dict:
    return {
        "type": "FeatureCollection",
        "updated": "2026-05-16T19:00:00+00:00",
        "features": list(alerts),
    }


# Zone "TXZ213" covers Houston; zone lookups are injected (no network in tests).
ZONES = {"TXZ213": square(*HOUSTON, 0.3), "TXZ192": square(*AUSTIN, 0.3)}


def resolve(zone_urls: list[str]) -> list[dict]:
    return [ZONES[url.rsplit("/", 1)[1]] for url in zone_urls]


def fail(_zone_urls: list[str]) -> list[dict]:
    raise RuntimeError("zone service down")


TORNADO = alert(
    "tor-1",
    "Tornado Warning",
    "2026-05-16T14:00:00-05:00",
    "2026-05-16T15:30:00-05:00",
    polygon=square(*HOUSTON, 0.05),
)
HEAT = alert(
    "heat-1",
    "Heat Advisory",
    "2026-05-16T10:00:00-05:00",
    "2026-05-16T20:00:00-05:00",
    zones=["TXZ213"],
)


def run(payload, at: datetime, zones=resolve):
    def fetch() -> dict:
        if isinstance(payload, Exception):
            raise payload
        return payload

    with SessionLocal() as db:
        result = take_snapshot(db, fetch=fetch, resolve_zones=zones, now=at)
        db.commit()
    return result


def active(at: datetime, h3: str = H8) -> list[str]:
    with SessionLocal() as db:
        cells = [db.get(Cell, h3)]
        return [s.id for s in active_alerts(db, cells, at)[h3]]


@pytest.fixture(autouse=True)
def cells():
    with SessionLocal() as db:
        seed_polygon(db, square(*HOUSTON, 0.004))
        seed_polygon(db, square(*AUSTIN, 0.004))
        db.commit()


def test_signal_expires_by_time_without_any_refresh():
    run(snapshot(TORNADO), t("14:02"))
    assert active(t("15:00")) == ["tor-1"]
    assert active(t("15:31")) == []  # ends 15:30; nothing was re-fetched


def test_signal_not_active_before_it_takes_effect():
    run(snapshot(TORNADO), t("13:50"))
    assert active(t("13:55")) == []


def test_successful_snapshot_supersedes_missing_alerts():
    run(snapshot(TORNADO, HEAT), t("14:05"))
    assert sorted(active(t("14:10"))) == ["heat-1", "tor-1"]
    run(snapshot(HEAT), t("14:20"))  # NWS cancelled the tornado warning early
    assert active(t("14:25")) == ["heat-1"]
    with SessionLocal() as db:
        from app.models import NwsAlert

        tor = db.get(NwsAlert, "tor-1")
        assert tor.superseded_at == t("14:20")
        assert tor.ends_at == t("15:30")  # NWS event time is kept as issued


def test_failed_snapshot_changes_nothing_and_goes_stale():
    run(snapshot(TORNADO), t("14:00"))
    # Without the tornado it would supersede it, but a zone lookup fails: incomplete.
    result = run(snapshot(HEAT), t("14:05"), zones=fail)
    assert not result.succeeded
    result = run(RuntimeError("HTTP 503"), t("14:10"))  # and the next fetch fails outright
    assert not result.succeeded
    assert active(t("14:15")) == ["tor-1"]
    with SessionLocal() as db:
        from app.models import NwsAlert, NwsAlertSnapshot

        tor = db.get(NwsAlert, "tor-1")
        assert (tor.last_seen_at, tor.superseded_at) == (t("14:00"), None)  # untouched
        attempts = db.query(NwsAlertSnapshot).order_by(NwsAlertSnapshot.fetched_at).all()
        assert [a.succeeded for a in attempts] == [True, False, False]
        assert alert_status(db, t("14:25")) == (t("14:00"), False)
        assert alert_status(db, t("14:31")) == (t("14:00"), True)  # > 30 min since success
    # Stale doesn't hide signals: still active until they end, flagged as possibly outdated.
    assert active(t("14:31")) == ["tor-1"]


def test_zone_based_alerts_keep_their_geometry_source():
    run(snapshot(TORNADO, HEAT), t("14:05"))
    with SessionLocal() as db:
        signals = {s.id: s for s in active_alerts(db, [db.get(Cell, H8)], t("14:10"))[H8]}
    assert signals["tor-1"].geometry_source == "alert"
    assert signals["heat-1"].geometry_source == "zones"
    assert signals["heat-1"].zones == ["TXZ213"]


def test_only_cells_inside_the_area_and_allowlisted_events_count():
    flood = alert(
        "ff-1",
        "Flash Flood Warning",
        "2026-05-16T14:00:00-05:00",
        "2026-05-16T18:00:00-05:00",
        polygon=square(*HOUSTON, 0.05),
    )
    result = run(snapshot(TORNADO, flood), t("14:05"))
    assert (result.alerts_total, result.signals_kept) == (2, 1)
    assert active(t("14:10"), A8) == []  # Austin is outside the tornado polygon


def test_reappearing_alert_is_active_again_and_keeps_first_seen():
    run(snapshot(HEAT), t("11:00"))
    run(snapshot(), t("11:05"))
    run(snapshot(HEAT), t("11:10"))
    assert active(t("11:15")) == ["heat-1"]
    with SessionLocal() as db:
        from app.models import NwsAlert

        heat = db.get(NwsAlert, "heat-1")
        assert (heat.first_seen_at, heat.last_seen_at, heat.superseded_at) == (
            t("11:00"),
            t("11:10"),
            None,
        )


def test_ends_falls_back_to_expires():
    watch = alert(
        "tw-1",
        "Tornado Watch",
        "2026-05-16T13:00:00-05:00",
        None,
        expires="2026-05-16T19:00:00-05:00",
        zones=["TXZ213"],
    )
    run(snapshot(watch), t("13:05"))
    assert active(t("18:59")) == ["tw-1"]
    assert active(t("19:00")) == []


def test_api_lists_active_signals_and_staleness(client):
    now = datetime.now(UTC)
    tornado = alert(
        "tor-live",
        "Tornado Warning",
        (now - timedelta(minutes=5)).isoformat(),
        (now + timedelta(minutes=40)).isoformat(),
        polygon=square(*HOUSTON, 0.05),
    )
    heat = alert(
        "heat-live",
        "Heat Advisory",
        (now - timedelta(hours=2)).isoformat(),
        (now + timedelta(hours=6)).isoformat(),
        zones=["TXZ213"],
    )
    run(snapshot(heat, tornado), now - timedelta(minutes=2))

    live = client.get(f"/need/cells/{H8}").json()["live"]["weather"]["alerts"]
    assert live["stale"] is False
    assert live["fetchedAt"] is not None
    by_id = {s["id"]: s for s in live["signals"]}
    assert set(by_id) == {"tor-live", "heat-live"}
    assert by_id["tor-live"]["category"] == "tornado"
    assert by_id["tor-live"]["geometrySource"] == "alert"
    assert by_id["heat-live"]["geometrySource"] == "zones"
    assert {
        "event",
        "severity",
        "certainty",
        "urgency",
        "headline",
        "effectiveAt",
        "endsAt",
        "firstSeenAt",
        "lastSeenAt",
    } <= set(by_id["tor-live"])

    features = client.get("/need/cells", params={"bbox": "-98.1,29.6,-95.2,30.5"}).json()
    props = {f["id"]: f["properties"] for f in features["features"]}
    assert props[H8]["activeAlerts"] == 2
    assert props[H8]["activeAlertCategory"] == "tornado"  # most severe of tornado + heat
    assert props[A8]["activeAlerts"] == 0
    assert props[A8]["activeAlertCategory"] is None


def test_api_reports_stale_when_no_snapshot_succeeded(client):
    live = client.get(f"/need/cells/{H8}").json()["live"]["weather"]["alerts"]
    assert live == {"fetchedAt": None, "stale": True, "signals": []}


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/nws"


def real_zone(_zone_urls: list[str]) -> list[dict]:
    # Inland Harris (TXZ213) as api.weather.gov returns it: a GeometryCollection of a
    # Polygon and a MultiPolygon.
    return [json.loads((FIXTURES / "forecast-TXZ213.json").read_text())]


def test_recorded_nws_payload_is_parsed_and_filtered():
    payload = json.loads((FIXTURES / "alerts-tx-2026-09-26.json").read_text())
    result = run(payload, t("14:00"))
    # Special Weather Statement, Flash Flood, Air Quality: none on the allowlist.
    assert (result.succeeded, result.alerts_total, result.signals_kept) == (True, 4, 0)


def test_real_zone_geometry_collection_becomes_a_valid_area():
    payload = json.loads((FIXTURES / "alerts-tx-2026-09-26.json").read_text())
    feature = copy.deepcopy(next(f for f in payload["features"] if f["geometry"] is None))
    feature["properties"].update(
        event="Heat Advisory",
        effective="2026-05-16T10:00:00-05:00",
        expires="2026-05-16T20:00:00-05:00",
        ends="2026-05-16T20:00:00-05:00",
        affectedZones=["https://api.weather.gov/zones/forecast/TXZ213"],
    )
    run(snapshot(feature), t("11:00"), zones=real_zone)
    assert active(t("12:00")) == [feature["properties"]["id"]]  # downtown Houston
    assert active(t("12:00"), A8) == []
    with SessionLocal() as db:
        valid = db.scalar(select(func.ST_IsValid(NwsAlert.geometry)))
    assert valid


def test_membership_uses_the_cell_center_not_any_overlap():
    # A small box over one corner of the Houston Cell: overlaps the hexagon, misses its center.
    lng, lat = max(geo.cell_to_polygon(H8)["coordinates"][0], key=lambda p: p[0])
    corner = {
        "type": "Polygon",
        "coordinates": [
            [
                [lng - 0.001, lat - 0.001],
                [lng + 0.01, lat - 0.001],
                [lng + 0.01, lat + 0.001],
                [lng - 0.001, lat + 0.001],
                [lng - 0.001, lat - 0.001],
            ]
        ],
    }
    clipped = alert(
        "tor-edge",
        "Tornado Warning",
        "2026-05-16T14:00:00-05:00",
        "2026-05-16T15:00:00-05:00",
        polygon=corner,
    )
    run(snapshot(clipped), t("14:01"))
    with SessionLocal() as db:
        area = select(NwsAlert.geometry).where(NwsAlert.id == "tor-edge")
        overlaps = db.scalar(
            select(func.ST_Intersects(area.scalar_subquery(), Cell.geometry)).where(
                Cell.h3_index == H8
            )
        )
    assert overlaps
    assert active(t("14:10")) == []


def test_a_write_failure_is_logged_and_changes_nothing():
    run(snapshot(TORNADO), t("14:00"))
    duplicate = snapshot(HEAT, HEAT)  # the same alert id twice: the upsert fails
    result = run(duplicate, t("14:05"))
    assert not result.succeeded and result.error
    assert active(t("14:10")) == ["tor-1"]
