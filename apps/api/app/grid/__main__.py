"""Grid data CLI. Run from apps/api:

uv run python -m app.grid backfill 2025 2026   # yearly public files, no auth
uv run python -m app.grid update               # recent days via ERCOT Public API
uv run python -m app.grid compute              # recompute zone metrics and scores
"""

import argparse
from datetime import UTC, date, datetime, timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.db import SessionLocal
from app.grid import sources
from app.grid.config import LEAD_BATTERIES_KW, battery, planner, scoring
from app.grid.dispatch import ceiling, simulate
from app.grid.metrics import per_year, score_zones, zone_metrics
from app.grid.sources import ERCOT_TZ
from app.grid.store import load_prices, upsert_prices
from app.grid.zones import REFERENCE_HUB, ZONES
from app.models import GridPrice, GridZoneMetrics


def backfill(years: list[int]) -> None:
    for year in years:
        for market in ("RT", "DA"):
            print(f"{market} {year}: downloading…", flush=True)
            df = sources.fetch_historical_year(market, year)
            print(f"{market} {year}: {upsert_prices(df):,} rows upserted", flush=True)


def update() -> None:
    api = sources.ErcotApi()
    try:
        with SessionLocal() as db:
            for market in ("RT", "DA"):
                last = db.scalar(
                    select(func.max(GridPrice.interval_start)).where(GridPrice.market == market)
                )
                # Re-fetch the last stored day in case it was partial.
                start = last.date() if last else date.today() - timedelta(days=7)
                df = api.fetch(market, start, date.today())
                print(f"{market} {start}..today: {upsert_prices(df):,} rows upserted")
    finally:
        api.close()


def full_years(rt: pd.Series) -> list[int]:
    """Local calendar years before this one with (nearly) every real-time interval."""
    counts = pd.Series(rt.index.tz_convert(ERCOT_TZ).year).value_counts()
    current = pd.Timestamp.now(tz=ERCOT_TZ).year
    return sorted(int(y) for y, n in counts.items() if y < current and n >= 0.98 * 365 * 96)


def battery_years(rt: pd.Series, da: pd.Series, sized: dict) -> list[dict]:
    """Realistic value of each battery size in each full past calendar year, so leads can
    show how much a year's value swings."""
    rt_year = rt.index.tz_convert(ERCOT_TZ).year
    da_year = da.index.tz_convert(ERCOT_TZ).year
    return [
        {
            "year": year,
            **{
                str(kwh): round(
                    float(simulate(rt[rt_year == year], da[da_year == year], b, planner).sum()),
                    2,
                )
                for kwh, b in sized.items()
            },
        }
        for year in full_years(rt)
    ]


def compute() -> None:
    end = pd.Timestamp.now(tz=UTC)
    prices = load_prices(pd.Timestamp("2000-01-01", tz=UTC), end)
    all_rt = prices[prices.market == "RT"].pivot(
        index="interval_start", columns="settlement_point", values="price"
    )
    all_da = prices[prices.market == "DA"].pivot(
        index="interval_start", columns="settlement_point", values="price"
    )
    # Use exactly the trailing window ending at the latest real-time interval.
    period_end = all_rt.index.max()
    period_start = period_end - pd.Timedelta(days=scoring.lookback_days)
    rt, da = all_rt[all_rt.index > period_start], all_da[all_da.index > period_start]

    metrics, series = {}, {}
    for zone in ZONES:
        zone_rt, zone_da = rt[zone.code].dropna(), da[zone.code].dropna()
        metrics[zone.code], series[zone.code] = zone_metrics(
            zone_rt, rt[REFERENCE_HUB].dropna(), zone_da, battery, planner, scoring
        )
        # Value of each battery size we pitch; leads use these per zone. The realistic
        # value is the day-ahead planner's; the ceiling is perfect hindsight.
        sized = {
            kwh: battery.model_copy(update={"capacity_kwh": kwh, "power_kw": kw})
            for kwh, kw in LEAD_BATTERIES_KW.items()
        }
        for kwh, b in sized.items():
            value = simulate(zone_rt, zone_da, b, planner).sum() * per_year(rt)
            metrics[zone.code][f"battery_value_{kwh}"] = float(value)
            metrics[zone.code][f"battery_ceiling_{kwh}"] = ceiling(zone_rt, b) * per_year(rt)
        series[zone.code]["battery_years"] = battery_years(
            all_rt[zone.code].dropna(), all_da[zone.code].dropna(), sized
        )
        m = metrics[zone.code]
        print(
            f"{zone.code}: ${m['arbitrage_usd']:,.0f}/battery/yr "
            f"(ceiling ${m['arbitrage_ceiling_usd']:,.0f})"
        )
    scores = score_zones(metrics, scoring)

    rows = [
        {
            "settlement_point": code,
            "period_start": period_start.to_pydatetime(),
            "period_end": period_end.to_pydatetime(),
            "grid_value_score": scores[code]["grid_value"],
            "metrics": metrics[code],
            "scores": scores[code],
            "series": series[code],
            "computed_at": datetime.now(UTC),
        }
        for code in metrics
    ]
    stmt = insert(GridZoneMetrics).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["settlement_point"],
        set_={c: stmt.excluded[c] for c in rows[0] if c != "settlement_point"},
    )
    with SessionLocal() as db:
        db.execute(stmt)
        db.commit()
    print(f"Scored {len(rows)} zones for {period_start:%Y-%m-%d} → {period_end:%Y-%m-%d}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.grid")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("backfill", help="load yearly historical price files")
    p.add_argument("years", nargs="+", type=int)
    sub.add_parser("update", help="load recent days via the ERCOT Public API")
    sub.add_parser("compute", help="recompute zone metrics and scores")
    args = parser.parse_args()

    if args.cmd == "backfill":
        backfill(args.years)
    elif args.cmd == "update":
        update()
    else:
        compute()


if __name__ == "__main__":
    main()
