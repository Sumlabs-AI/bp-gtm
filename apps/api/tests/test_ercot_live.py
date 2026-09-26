"""Parsing public ERCOT live data (dashboards and MIS price reports), no network."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from app.grid.sources import parse_mis_prices
from app.need.live.ercot import parse_condition

FIXTURES = Path(__file__).resolve().parent / "fixtures/ercot"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_condition_reads_official_state_reserves_and_forecast_margin():
    row = parse_condition(
        json.loads(fixture("daily-prc.json")), json.loads(fixture("supply-demand.json"))
    )
    assert (row["state"], row["title"], row["eea_level"]) == ("normal", "Normal Conditions", 0)
    assert row["prc_mw"] == 18957  # "18,957" in the feed
    assert row["source_updated_at"] == datetime(2026, 9, 26, 20, 24, 24, tzinfo=UTC)
    # Latest actual 5-minute interval, then the tightest forecast point for the rest of today.
    assert (row["capacity_mw"], row["demand_mw"]) == (102674, 77576)
    assert row["margin_forecast_min_mw"] > 0
    assert row["margin_forecast_min_at"] > datetime(2026, 9, 26, 20, 20, tzinfo=UTC)


def test_realtime_prices_keep_load_zones_and_hub_not_energy_weighted_duplicates():
    prices = parse_mis_prices("RT", fixture("rt-spp.csv"))
    assert set(prices["market"]) == {"RT"}
    houston = prices[prices["settlement_point"] == "LZ_HOUSTON"]
    assert len(houston) == 1  # LZ kept, LZEW dropped
    assert houston["price"].iloc[0] == 31.17
    # 09/26/2026 hour 16 interval 1 = 15:00 CDT = 20:00 UTC.
    assert houston["interval_start"].iloc[0] == pd.Timestamp("2026-09-26 20:00", tz="UTC")
    assert "HB_HUBAVG" in set(prices["settlement_point"])


def test_day_ahead_prices_are_hourly_from_hour_ending():
    prices = parse_mis_prices("DA", fixture("dam-spp.csv"))
    houston = prices[prices["settlement_point"] == "LZ_HOUSTON"].sort_values("interval_start")
    assert len(houston) == 24
    # Hour ending 01:00 on 09/27 = 00:00 CDT = 05:00 UTC.
    assert houston["interval_start"].iloc[0] == pd.Timestamp("2026-09-27 05:00", tz="UTC")
    assert houston["price"].dtype == float
