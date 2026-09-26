import pandas as pd

from app.grid.config import ScoringConfig
from app.grid.metrics import primary_reason, score_zones
from app.grid.sources import parse_historical


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
