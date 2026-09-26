"""Forecast Signals: our deterministic reading of NWS gridded forecasts and SPC outlooks."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.need.live.forecast import grid_signals, spc_signals

FIXTURES = Path(__file__).resolve().parent / "fixtures/nws"
NOW = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)


def f_to_c(f: float) -> float:
    return (f - 32) * 5 / 9


def mph_to_kmh(mph: float) -> float:
    return mph * 1.609344


def gridpoint(**layers: list[tuple[str, str, float | None]]) -> dict:
    """layers: variable -> [(start ISO, duration, value in NWS units)]."""
    props = {"updateTime": "2026-05-16T11:30:00+00:00"}
    uom = {
        "windGust": "wmoUnit:km_h-1",
        "heatIndex": "wmoUnit:degC",
        "temperature": "wmoUnit:degC",
        "iceAccumulation": "wmoUnit:mm",
    }
    for name, values in layers.items():
        props[name] = {
            "uom": uom[name],
            "values": [{"validTime": f"{s}/{d}", "value": v} for s, d, v in values],
        }
    return {"properties": props}


def by(signals, condition):
    return [s for s in signals if s["condition"] == condition]


def test_consecutive_hours_over_threshold_become_one_period():
    g = gridpoint(
        windGust=[
            ("2026-05-17T14:00:00+00:00", "PT2H", mph_to_kmh(50)),
            ("2026-05-17T16:00:00+00:00", "PT3H", mph_to_kmh(63)),
            ("2026-05-17T19:00:00+00:00", "PT1H", mph_to_kmh(47)),
            ("2026-05-17T20:00:00+00:00", "PT2H", mph_to_kmh(30)),
        ]
    )
    [wind] = by(grid_signals(g, NOW), "wind")
    assert wind["start_at"] == datetime(2026, 5, 17, 14, tzinfo=UTC)
    assert wind["end_at"] == datetime(2026, 5, 17, 20, tzinfo=UTC)
    assert wind["peak_value"] == pytest.approx(63)
    assert wind["unit"] == "mph"
    assert wind["level"] == "high"  # peak reached 58 mph
    assert wind["threshold"] == 46  # the elevated threshold that opened the period
    assert wind["source"] == "nws_grid"
    assert wind["source_updated_at"] == datetime(2026, 5, 16, 11, 30, tzinfo=UTC)


def test_a_gap_below_threshold_splits_periods_and_levels_follow_peaks():
    g = gridpoint(
        heatIndex=[
            ("2026-05-16T19:00:00+00:00", "PT2H", f_to_c(106)),
            ("2026-05-16T21:00:00+00:00", "PT3H", f_to_c(98)),
            ("2026-05-17T00:00:00+00:00", "PT19H", None),  # missing values are ignored
            ("2026-05-17T19:00:00+00:00", "PT3H", f_to_c(112)),
        ]
    )
    heat = by(grid_signals(g, NOW), "heat")
    assert [h["level"] for h in heat] == ["elevated", "high"]
    assert heat[0]["end_at"] == datetime(2026, 5, 16, 21, tzinfo=UTC)


def test_cold_is_at_or_below_and_uses_air_temperature():
    g = gridpoint(
        temperature=[
            ("2026-05-17T08:00:00+00:00", "PT4H", f_to_c(27)),
            ("2026-05-17T12:00:00+00:00", "PT2H", f_to_c(19)),
            ("2026-05-17T14:00:00+00:00", "PT2H", f_to_c(35)),
        ]
    )
    [cold] = by(grid_signals(g, NOW), "cold")
    assert (cold["level"], cold["unit"], cold["threshold"]) == ("high", "°F", 28)
    assert cold["peak_value"] == pytest.approx(19)  # the most extreme (lowest) value
    assert cold["end_at"] - cold["start_at"] == timedelta(hours=6)


def test_ice_is_judged_per_forecast_interval():
    g = gridpoint(
        iceAccumulation=[
            ("2026-05-17T00:00:00+00:00", "PT6H", 1.0),  # 0.04 in: below
            ("2026-05-17T06:00:00+00:00", "PT6H", 3.0),  # 0.12 in: elevated
            ("2026-05-17T12:00:00+00:00", "PT6H", 7.0),  # 0.28 in: high
        ]
    )
    [ice] = by(grid_signals(g, NOW), "ice")
    assert (ice["start_at"], ice["end_at"]) == (
        datetime(2026, 5, 17, 6, tzinfo=UTC),
        datetime(2026, 5, 17, 18, tzinfo=UTC),
    )
    assert ice["level"] == "high" and ice["unit"] == "in"


def test_periods_are_kept_up_to_the_storage_horizon_and_in_progress_keep_their_start():
    g = gridpoint(
        windGust=[
            ("2026-05-16T09:00:00+00:00", "PT5H", mph_to_kmh(60)),  # started before now
            ("2026-05-18T14:00:00+00:00", "PT2H", mph_to_kmh(60)),  # +50 h: stored, not Active
            ("2026-05-19T14:00:00+00:00", "PT2H", mph_to_kmh(60)),  # +74 h: beyond storage
        ]
    )
    winds = by(grid_signals(g, NOW), "wind")
    assert [w["start_at"].day for w in winds] == [16, 18]
    wind = winds[0]
    assert wind["start_at"] == datetime(2026, 5, 16, 9, tzinfo=UTC)
    assert wind["end_at"] == datetime(2026, 5, 16, 14, tzinfo=UTC)


def test_periods_already_over_are_dropped():
    g = gridpoint(windGust=[("2026-05-16T06:00:00+00:00", "PT3H", mph_to_kmh(60))])
    assert grid_signals(g, NOW) == []


def test_recorded_houston_gridpoint_parses():
    g = json.loads((FIXTURES / "gridpoint-HGX-63-95.json").read_text())
    now = datetime(2026, 9, 26, 18, 30, tzinfo=UTC)
    signals = grid_signals(g, now)
    # A mild late-September forecast: parsed without error, nothing dangerous.
    assert all(s["start_at"] < now + timedelta(hours=48) for s in signals)
    assert {s["condition"] for s in signals} <= {"wind", "heat", "cold", "ice"}


def outlook(*areas: tuple[str, float]) -> dict:
    """Nested square areas centred on Houston: (label, half-size in degrees)."""
    features = []
    for label, d in areas:
        ring = [
            [-95.37 - d, 29.76 - d],
            [-95.37 + d, 29.76 - d],
            [-95.37 + d, 29.76 + d],
            [-95.37 - d, 29.76 + d],
            [-95.37 - d, 29.76 - d],
        ]
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "MultiPolygon", "coordinates": [[ring]]},
                "properties": {
                    "LABEL": label,
                    "VALID_ISO": "2026-05-16T13:00:00+00:00",
                    "EXPIRE_ISO": "2026-05-17T12:00:00+00:00",
                    "ISSUE_ISO": "2026-05-16T12:45:00+00:00",
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def test_spc_takes_the_highest_category_covering_each_point():
    points = {"houston": (29.76, -95.37), "edge": (29.76, -94.95), "austin": (30.27, -97.74)}
    day1 = outlook(("TSTM", 3.0), ("MRGL", 2.0), ("SLGT", 1.0), ("ENH", 0.2))
    signals = {s["h3_index"]: s for s in spc_signals([day1], points)}
    assert signals["houston"]["label"] == "ENH" and signals["houston"]["level"] == "high"
    assert signals["edge"]["label"] == "SLGT" and signals["edge"]["level"] == "elevated"
    assert "austin" not in signals  # only Marginal/TSTM there: not a signal
    s = signals["houston"]
    assert (s["source"], s["condition"]) == ("spc_outlook", "severe_storm")
    assert s["source_updated_at"] == datetime(2026, 5, 16, 12, 45, tzinfo=UTC)
    assert s["start_at"] == datetime(2026, 5, 16, 13, tzinfo=UTC)


def test_recorded_quiet_spc_outlook_gives_no_signals():
    day1 = json.loads((FIXTURES / "spc-day1-cat.json").read_text())  # TSTM + MRGL only
    assert spc_signals([day1], {"houston": (29.76, -95.37)}) == []


def test_intervals_not_on_the_hour_never_overlap():
    g = gridpoint(
        windGust=[
            ("2026-05-17T10:30:00+00:00", "PT90M", mph_to_kmh(60)),
            ("2026-05-17T12:00:00+00:00", "PT1H", mph_to_kmh(60)),
        ]
    )
    [wind] = by(grid_signals(g, NOW), "wind")  # one period, not two overlapping ones
    assert (wind["start_at"], wind["end_at"]) == (
        datetime(2026, 5, 17, 10, 30, tzinfo=UTC),
        datetime(2026, 5, 17, 13, tzinfo=UTC),
    )


def test_multi_day_durations_are_understood():
    g = gridpoint(temperature=[("2026-05-16T13:00:00+00:00", "P1DT2H", f_to_c(25))])
    [cold] = by(grid_signals(g, NOW), "cold")
    assert cold["end_at"] == datetime(2026, 5, 17, 15, tzinfo=UTC)


def test_unknown_duration_or_unit_fails_loudly():
    with pytest.raises(ValueError, match="duration"):
        grid_signals(gridpoint(windGust=[("2026-05-17T10:00:00+00:00", "P1Y", 100)]), NOW)
    g = gridpoint(windGust=[("2026-05-17T10:00:00+00:00", "PT1H", 100)])
    g["properties"]["windGust"]["uom"] = "wmoUnit:m_s-1"
    with pytest.raises(ValueError, match="unit"):
        grid_signals(g, NOW)


def test_level_reflects_the_part_not_over_yet():
    g = gridpoint(
        windGust=[
            ("2026-05-16T09:00:00+00:00", "PT2H", mph_to_kmh(65)),  # past: high
            ("2026-05-16T11:00:00+00:00", "PT4H", mph_to_kmh(50)),  # now and later: elevated
        ]
    )
    [wind] = by(grid_signals(g, NOW), "wind")
    assert wind["start_at"] == datetime(2026, 5, 16, 9, tzinfo=UTC)  # real start kept
    assert (wind["level"], wind["peak_value"]) == ("elevated", pytest.approx(50))
