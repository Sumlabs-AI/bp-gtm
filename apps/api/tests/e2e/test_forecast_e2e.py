"""Forecast Signals end to end: per-point runs -> signals -> Active for res-8 Cells."""

from datetime import UTC, datetime, timedelta

import pytest

from app import geo
from app.db import SessionLocal
from app.models import Cell, ForecastPoint, ForecastSignal
from app.need.live.forecast_store import active_forecast, forecast_status, take_forecast_run
from app.need.store import seed_polygon

HOUSTON = (29.7604, -95.3698)
AUSTIN = (30.2672, -97.7431)
H8, A8 = geo.latlng_to_cell(*HOUSTON), geo.latlng_to_cell(*AUSTIN)
H6, A6 = geo.cell_to_parent(H8, 6), geo.cell_to_parent(A8, 6)
T0 = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)


def square(lat: float, lng: float, d: float = 0.004) -> dict:
    ring = [[lng - d, lat - d], [lng + d, lat - d], [lng + d, lat + d], [lng - d, lat + d]]
    return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}


def gust(start: datetime, hours: int, mph: float, updated: datetime) -> dict:
    return {
        "properties": {
            "updateTime": updated.isoformat(),
            "windGust": {
                "values": [
                    {"validTime": f"{start.isoformat()}/PT{hours}H", "value": mph * 1.609344}
                ]
            },
        }
    }


def outlook(label: str, valid: datetime, expire: datetime) -> dict:
    d = 3.0  # covers both cities
    ring = [
        [-96.5 - d, 30 - d],
        [-96.5 + d, 30 - d],
        [-96.5 + d, 30 + d],
        [-96.5 - d, 30 + d],
        [-96.5 - d, 30 - d],
    ]
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {
                    "LABEL": label,
                    "VALID_ISO": valid.isoformat(),
                    "EXPIRE_ISO": expire.isoformat(),
                    "ISSUE_ISO": valid.isoformat(),
                },
            }
        ],
    }


@pytest.fixture(autouse=True)
def points():
    with SessionLocal() as db:
        for lat, lng in (HOUSTON, AUSTIN):
            seed_polygon(db, square(lat, lng))
        for h6, (lat, lng), grid in (
            (H6, HOUSTON, ("HGX", 63, 95)),
            (A6, AUSTIN, ("EWX", 156, 91)),
        ):
            db.add(
                ForecastPoint(
                    h3_index=h6, lat=lat, lng=lng, office=grid[0], grid_x=grid[1], grid_y=grid[2]
                )
            )
        db.commit()


def run(at: datetime, grids: dict, spc):
    def fetch_grid(point: ForecastPoint) -> dict:
        result = grids[point.h3_index]
        if isinstance(result, Exception):
            raise result
        return result

    def fetch_spc() -> list[dict]:
        if isinstance(spc, Exception):
            raise spc
        return spc

    with SessionLocal() as db:
        result = take_forecast_run(db, fetch_grid=fetch_grid, fetch_spc=fetch_spc, now=at)
        db.commit()
    return result


def active(at: datetime, h3: str = H8) -> list[tuple[str, str]]:
    with SessionLocal() as db:
        signals = active_forecast(db, [db.get(Cell, h3)], at)[h3]
        return sorted((s.source, s.condition) for s in signals)


def windy(at: datetime, updated: datetime) -> dict:
    return gust(at + timedelta(hours=20), 6, 62, updated)


def calm(updated: datetime) -> dict:
    return {"properties": {"updateTime": updated.isoformat(), "windGust": {"values": []}}}


def test_signals_apply_to_res8_cells_through_their_res6_point():
    run(T0, {H6: windy(T0, T0), A6: calm(T0)}, [])
    assert active(T0) == [("nws_grid", "wind")]
    assert active(T0, A8) == []


def test_a_failed_point_keeps_its_signals_and_a_successful_one_replaces():
    run(T0, {H6: windy(T0, T0), A6: windy(T0, T0)}, [])
    later = T0 + timedelta(hours=1)
    result = run(later, {H6: RuntimeError("HTTP 500"), A6: calm(later)}, [])
    assert (result.points_ok, result.points_failed) == (1, 1)
    assert active(later) == [("nws_grid", "wind")]  # Houston failed: previous forecast kept
    assert active(later, A8) == []  # Austin succeeded with calm: its wind signal replaced
    with SessionLocal() as db:
        replaced = db.query(ForecastSignal).filter(ForecastSignal.replaced_at.is_not(None)).all()
        assert [s.replaced_at for s in replaced] == [later]  # kept for history, not deleted


def test_signals_expire_by_time_and_respect_the_horizon():
    run(T0, {H6: gust(T0 + timedelta(hours=2), 3, 62, T0), A6: calm(T0)}, [])
    assert active(T0 + timedelta(hours=4)) == [("nws_grid", "wind")]
    assert active(T0 + timedelta(hours=5)) == []  # period ended at +5 h


def test_spc_failure_keeps_previous_outlook_signals():
    day1 = outlook("ENH", T0, T0 + timedelta(hours=24))
    run(T0, {H6: calm(T0), A6: calm(T0)}, [day1])
    assert active(T0) == [("spc_outlook", "severe_storm")]
    later = T0 + timedelta(hours=1)
    result = run(later, {H6: calm(later), A6: calm(later)}, RuntimeError("SPC down"))
    assert not result.spc_ok
    assert active(later) == [("spc_outlook", "severe_storm")]
    run(later + timedelta(hours=1), {H6: calm(later), A6: calm(later)}, [])  # SPC ok, none
    assert active(later + timedelta(hours=1)) == []


def test_per_point_staleness_and_update_time_kept_apart_from_fetch_time():
    issued = T0 - timedelta(minutes=40)
    run(T0, {H6: windy(T0, issued), A6: calm(T0)}, [])
    run(T0 + timedelta(hours=2), {H6: RuntimeError("down"), A6: calm(T0)}, [])
    with SessionLocal() as db:
        status = forecast_status(db, [H6, A6], T0 + timedelta(hours=3, minutes=1))
    houston = status["grid"][H6]
    assert houston["fetched_at"] == T0
    assert houston["source_updated_at"] == issued
    assert houston["stale"] is True  # last success > 3 h ago
    assert status["grid"][A6]["stale"] is False
    assert status["spc"]["stale"] is False


def test_api_keeps_forecast_separate_from_alerts(client):
    now = datetime.now(UTC)
    run(now, {H6: windy(now, now), A6: calm(now)}, [])
    live = client.get(f"/need/cells/{H8}").json()["live"]["weather"]
    assert live["alerts"]["signals"] == []  # no official alert: forecast isn't one
    forecast = live["forecast"]
    assert (forecast["resolution"], forecast["sourceCell"]) == (6, H6)
    assert forecast["horizonHours"] == 48
    assert forecast["grid"]["stale"] is False
    [signal] = forecast["signals"]
    assert (signal["source"], signal["condition"], signal["level"]) == ("nws_grid", "wind", "high")
    assert signal["threshold"] == 46 and signal["unit"] == "mph"
    assert 19 <= signal["leadHours"] <= 20

    features = client.get("/need/cells", params={"bbox": "-98.1,29.6,-95.2,30.5"}).json()
    props = {f["id"]: f["properties"] for f in features["features"]}
    assert (props[H8]["activeForecastSignals"], props[H8]["forecastLevel"]) == (1, "high")
    assert (props[A8]["activeForecastSignals"], props[A8]["forecastLevel"]) == (0, None)
    assert props[H8]["activeAlerts"] == 0
