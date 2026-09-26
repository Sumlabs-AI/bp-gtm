import pandas as pd
import pytest

from app.grid.config import BatteryConfig, ScoringConfig
from app.grid.metrics import backtest_daily, primary_reason, score_zones
from app.grid.sources import parse_historical


def day_prices(values: list[float]) -> pd.Series:
    idx = pd.date_range("2026-06-01", periods=len(values), freq="15min", tz="America/Chicago")
    return pd.Series(values, index=idx.tz_convert("UTC"))


def test_backtest_single_cycle():
    # 1 kWh steps, 2 steps of capacity, lossless: buy 2 intervals at $10, sell 2 at $110.
    battery = BatteryConfig(capacity_kwh=2, power_kw=4, round_trip_efficiency=1.0)
    prices = day_prices([10, 10, 50, 110, 110, 50])
    value = backtest_daily(prices, battery).iloc[0]
    assert value == pytest.approx(2 * (110 - 10) / 1000)


def test_backtest_respects_order_and_efficiency():
    battery = BatteryConfig(capacity_kwh=1, power_kw=4, round_trip_efficiency=0.5)
    # Expensive first, cheap later: a battery that starts empty can't profit.
    assert backtest_daily(day_prices([100, 1]), battery).iloc[0] == 0
    # Spread of 2x exactly cancels 50% efficiency.
    assert backtest_daily(day_prices([10, 20]), battery).iloc[0] == pytest.approx(0)


def test_scores_are_relative_and_weighted():
    metrics = {
        "A": {
            "arbitrage_usd": 100,
            "congestion_premium": 1,
            "scarcity_hours": 0,
            "surprise": 5,
            "negative_price_pct": 1,
        },
        "B": {
            "arbitrage_usd": 300,
            "congestion_premium": 1,
            "scarcity_hours": 10,
            "surprise": 10,
            "negative_price_pct": 3,
        },
    }
    scores = score_zones(metrics, ScoringConfig())
    assert scores["A"]["arbitrage"] == 0 and scores["B"]["arbitrage"] == 100
    assert scores["A"]["congestion"] == scores["B"]["congestion"] == 50  # no spread
    assert scores["B"]["grid_value"] > scores["A"]["grid_value"]


def test_primary_reason():
    weights = ScoringConfig().weights
    top = {"arbitrage": 90, "congestion": 80, "scarcity": 0, "surprise": 0, "negative_prices": 0}
    assert primary_reason(top, weights).startswith("High battery arbitrage value and local")
    assert primary_reason(dict.fromkeys(weights, 10), weights).startswith("No standout")


def test_parse_historical_handles_dst_fall_back():
    raw = pd.DataFrame(
        {
            "Delivery Date": ["11/02/2025"] * 2,
            "Delivery Hour": [2, 2],
            "Delivery Interval": [1, 1],
            "Repeated Hour Flag": ["N", "Y"],
            "Settlement Point Name": ["LZ_NORTH"] * 2,
            "Settlement Point Price": [20.0, 21.0],
        }
    )
    out = parse_historical("RT", raw)
    # 01:00 CDT and 01:00 CST are an hour apart in UTC.
    assert list(out.interval_start.dt.strftime("%H:%M")) == ["06:00", "07:00"]
