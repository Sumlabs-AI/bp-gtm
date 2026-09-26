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
from app.grid.config import battery, scoring
from app.grid.metrics import score_zones, zone_metrics
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


def compute() -> None:
    end = pd.Timestamp.now(tz=UTC)
    prices = load_prices(end - pd.Timedelta(days=scoring.lookback_days + 1), end)
    rt = prices[prices.market == "RT"].pivot(
        index="interval_start", columns="settlement_point", values="price"
    )
    da = prices[prices.market == "DA"].pivot(
        index="interval_start", columns="settlement_point", values="price"
    )
    # Use exactly the trailing window ending at the latest real-time interval.
    period_end = rt.index.max()
    period_start = period_end - pd.Timedelta(days=scoring.lookback_days)
    rt, da = rt[rt.index > period_start], da[da.index > period_start]

    metrics, series = {}, {}
    for zone in ZONES:
        metrics[zone.code], series[zone.code] = zone_metrics(
            rt[zone.code].dropna(),
            rt[REFERENCE_HUB].dropna(),
            da[zone.code].dropna(),
            battery,
            scoring,
        )
        print(f"{zone.code}: ${metrics[zone.code]['arbitrage_usd']:,.0f}/battery/yr")
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
