"""Grid economics metrics. Pure functions over price series; no DB access here."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.grid.config import BatteryConfig, ScoringConfig
from app.grid.sources import ERCOT_TZ

INTERVAL_H = 0.25  # real-time settlement interval


@dataclass(frozen=True)
class Driver:
    key: str
    metric: str  # key in the metrics dict that gets scored
    label: str
    unit: str
    explain: str  # formatted with the metric value as {v}
    reason: str  # phrase used in the primary-reason sentence


DRIVERS = [
    Driver(
        "arbitrage",
        "arbitrage_usd",
        "Battery arbitrage",
        "$/battery/yr",
        "One Base battery would have earned about ${v:,.0f} over the last year by charging "
        "when real-time power was cheap and discharging when it was expensive.",
        "high battery arbitrage value",
    ),
    Driver(
        "congestion",
        "congestion_premium",
        "Congestion premium",
        "$/MWh",
        "Power here costs on average ${v:,.2f}/MWh more than the ERCOT hub average when "
        "it separates upward, a sign of local transmission constraints.",
        "local prices that break above the rest of the grid",
    ),
    Driver(
        "scarcity",
        "scarcity_hours",
        "Scarcity hours",
        "h/yr",
        "Real-time prices hit scarcity levels (≥ $1,000/MWh) for {v:,.1f} hours in the "
        "last year; a few hours like these can make a battery's year.",
        "frequent scarcity pricing",
    ),
    Driver(
        "surprise",
        "surprise",
        "Grid surprise",
        "$/MWh",
        "Real-time prices missed the day-ahead price by ${v:,.2f}/MWh on average. Flexible "
        "batteries earn from these surprises; scheduled resources can't.",
        "large gaps between day-ahead and real-time prices",
    ),
    Driver(
        "negative_prices",
        "negative_price_pct",
        "Negative prices",
        "% of intervals",
        "Power was free or negatively priced {v:,.1f}% of the time, so batteries can "
        "charge at no cost (or get paid to).",
        "frequent free or negative-price charging",
    ),
]
DRIVERS_BY_KEY = {d.key: d for d in DRIVERS}


def backtest_daily(prices: pd.Series, battery: BatteryConfig) -> pd.Series:
    """Best-possible daily arbitrage value ($) with perfect hindsight.

    Dynamic program over state of charge per local day, starting and ending empty.
    Charge/discharge move one power step per 15-minute interval; efficiency losses are
    charged on the way in. This is a historical upper bound, not a forecast.
    """
    step_kwh = battery.power_kw * INTERVAL_H
    n = int(battery.capacity_kwh // step_kwh)  # number of state-of-charge steps
    step_mwh = step_kwh / 1000
    local = prices.tz_convert(ERCOT_TZ)

    values = {}
    for day, day_prices in local.groupby(local.index.date):
        v = np.full(n + 1, -np.inf)
        v[0] = 0.0  # must end the day empty
        for p in day_prices.to_numpy()[::-1]:
            new = v.copy()
            new[:-1] = np.maximum(new[:-1], v[1:] - p * step_mwh / battery.round_trip_efficiency)
            new[1:] = np.maximum(new[1:], v[:-1] + p * step_mwh)
            v = new
        values[pd.Timestamp(day)] = v[0]
    return pd.Series(values, dtype=float)


def zone_metrics(
    rt: pd.Series, hub_rt: pd.Series, da: pd.Series, battery: BatteryConfig, cfg: ScoringConfig
) -> tuple[dict, dict]:
    """Raw metrics and chart series for one zone. Series are indexed by UTC interval start."""
    days = max((rt.index.max() - rt.index.min()).total_seconds() / 86400, 1)
    per_year = 365 / days

    daily = backtest_daily(rt, battery)
    local = rt.tz_convert(ERCOT_TZ)
    k = cfg.spread_hours * 4
    spreads = local.groupby(local.index.date).apply(
        lambda s: s.nlargest(k).mean() - s.nsmallest(k).mean()
    )
    basis = (rt - hub_rt).dropna()
    rt_hourly = rt.resample("1h").mean()
    miss = (rt_hourly - da).dropna().abs()
    top10 = daily.nlargest(10).sum() / daily.sum() if daily.sum() > 0 else 0.0

    metrics = {
        "arbitrage_usd": float(daily.sum() * per_year),
        "congestion_premium": float(basis.clip(lower=0).mean()),
        "scarcity_hours": float((rt >= cfg.scarcity_threshold).sum() * INTERVAL_H * per_year),
        "surprise": float(miss.mean()),
        "negative_price_pct": float((rt < 0).mean() * 100),
        # Context, not scored:
        "avg_price": float(rt.mean()),
        "volatility": float(rt.std()),
        "daily_spread": float(spreads.mean()),
        "avg_basis": float(basis.mean()),
        "top10_days_share": float(top10 * 100),
    }

    hub_local = hub_rt.tz_convert(ERCOT_TZ)
    profile = pd.DataFrame(
        {
            "zone": local.groupby(local.index.hour).mean(),
            "hub": hub_local.groupby(hub_local.index.hour).mean(),
        }
    )
    monthly_value = daily.groupby(daily.index.to_period("M")).sum()
    basis_local = basis.tz_convert(ERCOT_TZ)
    monthly_basis = basis_local.groupby(basis_local.index.strftime("%Y-%m")).mean()
    series = {
        "hourly_profile": [
            {"hour": int(h), "zone": round(r.zone, 2), "hub": round(r.hub, 2)}
            for h, r in profile.iterrows()
        ],
        "monthly": [
            {
                "month": str(m),
                "arbitrage_usd": round(float(v), 2),
                "avg_basis": round(float(monthly_basis.get(str(m), np.nan)), 2),
            }
            for m, v in monthly_value.items()
        ],
    }
    return metrics, series


def score_zones(metrics: dict[str, dict], cfg: ScoringConfig) -> dict[str, dict]:
    """0-100 driver scores, min-max normalized across zones, plus the weighted composite.

    Scores are relative: 100 = best of the ERCOT load zones, 0 = worst.
    """
    scores: dict[str, dict] = {code: {} for code in metrics}
    for d in DRIVERS:
        values = {code: m[d.metric] for code, m in metrics.items()}
        lo, hi = min(values.values()), max(values.values())
        for code, v in values.items():
            scores[code][d.key] = 50.0 if hi == lo else round((v - lo) / (hi - lo) * 100, 1)

    total = sum(cfg.weights.values())
    for s in scores.values():
        s["grid_value"] = round(sum(cfg.weights[k] * s[k] for k in cfg.weights) / total, 1)
    return scores


def primary_reason(scores: dict, weights: dict[str, float]) -> str:
    """Deterministic one-sentence explanation from the two strongest weighted drivers."""
    ranked = sorted(weights, key=lambda k: weights[k] * scores[k], reverse=True)
    strong = [DRIVERS_BY_KEY[k].reason for k in ranked[:2] if scores[k] >= 50]
    if not strong:
        return "No standout driver compared with the other ERCOT load zones."
    return (" and ".join(strong) + ".").capitalize()
