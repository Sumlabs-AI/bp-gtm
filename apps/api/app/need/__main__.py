"""Need Engine CLI. Run from apps/api:

uv run python -m app.need seed                     # every Market (idempotent)
uv run python -m app.need seed --market harris
uv run python -m app.need enrich                   # recompute every Cell's load zone + county
uv run python -m app.need outage download         # EAGLE-I + EIA-861 (cached, multi-GB)
uv run python -m app.need outage compute          # Parquet -> county/utility features
uv run python -m app.need outage validate         # known storms + SAIDI cross-check
uv run python -m app.need weather download        # IEM warnings + nClimGrid (cached)
uv run python -m app.need weather compute         # res-6 Storm + county Temperature
uv run python -m app.need weather validate        # storm days by year, known storms
uv run python -m app.need export --out cells.csv        # h3_index, resolution, center (for ML)
"""

import argparse
import csv
import time
from pathlib import Path

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Cell
from app.need.enrich import enrich_counties, enrich_load_zones
from app.need.markets import MARKETS, MARKETS_BY_NAME
from app.need.store import seed_polygon


def seed(names: list[str]) -> None:
    for name in names:
        market = MARKETS_BY_NAME[name]
        with SessionLocal() as db:
            report = seed_polygon(db, market.geometry())
            db.commit()
        print(
            f"Market:      {market.label} ({market.geoid})\n"
            f"Resolution:  {report.resolution}\n"
            f"Generated:   {report.generated:,}\n"
            f"Inserted:    {report.inserted:,}\n"
            f"Existing:    {report.existing:,}\n"
            f"Duration:    {report.seconds:.2f}s\n"
        )
    # New Cells get their static geography right away.
    enrich()


def enrich() -> None:
    for title, run in (("Load Zone", enrich_load_zones), ("County", enrich_counties)):
        with SessionLocal() as db:
            report = run(db)
            db.commit()
        rows = [
            ("Cells processed", report.processed),
            ("Assigned", report.assigned),
            ("Unknown", report.unknown),
            None,
            *report.by_value.items(),
            None,
            ("Changed", report.changed),
        ]
        print(f"{title} Enrichment\n" + "─" * 30)
        for row in rows:
            print(f"{row[0] + ':':<20}{row[1]:>10,}" if row else "")
        print(f"\n{'Duration:':<20}{report.seconds:>9.2f}s\n")


def outage(action: str) -> None:
    from app.need.outage import pipeline  # heavy imports (duckdb) only when needed

    if action == "download":
        pipeline.download()
    elif action == "compute":
        started = time.perf_counter()
        r = pipeline.compute()
        print(
            f"Baseline Outage Need\n{'─' * 30}\n"
            f"{'EAGLE-I Texas rows:':<24}{r.parquet_rows:>12,}\n"
            f"{'Data through:':<24}{r.data_through!s:>12}\n"
            f"{'Counties:':<24}{r.counties:>12,}\n"
            f"{'  in Reference Pop.:':<24}{r.counties_in_reference:>12,}\n"
            f"{'Utilities:':<24}{r.utilities:>12,}\n"
            f"{'  ranked (SAIDI):':<24}{r.utilities_ranked:>12,}\n"
            f"\n{'Duration:':<24}{time.perf_counter() - started:>11.1f}s"
        )
    else:
        from app.need.config import UTILITY_BY_COUNTY, UTILITY_BY_LOAD_ZONE

        utility_by_market = {
            "48201": UTILITY_BY_COUNTY["48201"],
            "48453": UTILITY_BY_LOAD_ZONE["LZ_AEN"],
        }
        for market in MARKETS:
            events = pipeline.major_events(market.geoid)
            print(f"\n{market.label}: {len(events)} Major Outage Events")
            for e in events.itertuples():
                print(
                    f"  {e.start:%Y-%m-%d %H:%M} → {e.end:%Y-%m-%d %H:%M}  "
                    f"peak {e.peak_pct_out:6.1%}  {e.hours_per_customer:5.2f} h/customer"
                )
            table = pipeline.yearly_events(market.geoid)
            table["eaglei_min_per_customer"] = pipeline.yearly_hours_per_customer(market.geoid) * 60
            table["eia_saidi_with_med"] = pipeline.utility_saidi(utility_by_market[market.geoid])
            print(table.round(0).astype("Int64").to_string())


def weather(action: str) -> None:
    from app.need.weather import pipeline  # heavy imports (geopandas) only when needed

    if action == "download":
        pipeline.download()
        return
    started = time.perf_counter()
    if action == "compute":
        report = pipeline.compute()
        print(
            f"Baseline Weather Need\n{'─' * 30}\n"
            f"{'SV/TO/EW warnings:':<24}{report.warnings:>12,}\n"
            f"{'Texas res-6 cells:':<24}{report.grid_cells:>12,}\n"
            f"{'Storm data through:':<24}{report.storm_data_through!s:>12}\n"
            f"{'Counties (temperature):':<24}{report.counties:>12,}\n"
            f"{'Temp. data through:':<24}{report.temperature_data_through!s:>12}\n"
            f"\n{'Duration:':<24}{time.perf_counter() - started:>11.1f}s"
        )
        return
    import pandas as pd

    from app import geo
    from app.need.markets import county_for_points

    hits, storms = pipeline.build_storms()
    temperature = pipeline.build_temperature().set_index("county_fips")
    centers = pd.DataFrame(
        [(h, *geo.cell_to_center(h)) for h in storms["h3_index"]], columns=["h3", "lat", "lng"]
    )
    centers["county"] = county_for_points(centers["lat"], centers["lng"])
    for market in MARKETS:
        cells = set(centers.loc[centers["county"] == market.geoid, "h3"])
        mine = hits[hits["h3_index"].isin(cells)]
        by_year = mine.groupby(pd.to_datetime(mine["day"]).dt.year)["day"].nunique()
        print(f"\n{market.label}: {len(cells)} res-6 cells; warning-days (any cell) by year:")
        print("  " + ", ".join(f"{y}: {n}" for y, n in by_year.items()))
        for label, day in (("Derecho", "2024-05-16"), ("Beryl", "2024-07-08")):
            hit = (mine["day"].astype(str) == day).any()
            print(f"  {label} {day}: {'warned' if hit else 'no SV/TO/EW warning'}")
        s = storms[storms["h3_index"].isin(cells)]
        print(
            f"  Storm Exposure across its cells: min {s.storm_exposure.min():.0f}, "
            f"median {s.storm_exposure.median():.0f}, max {s.storm_exposure.max():.0f}"
        )
        t = temperature.loc[market.geoid]
        print(
            f"  Temperature (5 y through {t.data_through}): {t.heat_days_100f_5y} days >= 100F, "
            f"{t.heat_days_95f_5y} >= 95F, {t.cold_days_28f_5y} <= 28F, "
            f"{t.cold_days_32f_5y} <= 32F -> exposure {t.temperature_exposure:.1f}"
        )
    top = storms.nlargest(10, "warning_days_5y").merge(centers, left_on="h3_index", right_on="h3")
    print("\nTop 10 Texas res-6 cells by warning-days (5 y):")
    for r in top.itertuples():
        print(f"  {r.h3_index}  {r.lat:6.2f},{r.lng:8.2f}  {r.warning_days_5y} days")


def export(out: Path) -> None:
    columns = ("h3_index", "resolution", "center_lat", "center_lng")
    with SessionLocal() as db, out.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        rows = db.execute(select(*(getattr(Cell, c) for c in columns)).order_by(Cell.h3_index))
        writer.writerows(rows)
        count = db.scalar(select(func.count()).select_from(Cell))
    print(f"Wrote {count:,} cells to {out}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.need")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("seed", help="create the Cells covering Markets")
    p.add_argument(
        "--market",
        action="append",
        choices=[m.name for m in MARKETS],
        help="repeatable; default: every Market",
    )
    sub.add_parser("enrich", help="recompute every Cell's load zone")
    p = sub.add_parser("outage", help="Baseline Outage Need pipeline")
    p.add_argument("action", choices=["download", "compute", "validate"])
    p = sub.add_parser("weather", help="Baseline Weather Need pipeline")
    p.add_argument("action", choices=["download", "compute", "validate"])
    p = sub.add_parser("export", help="write all Cells to CSV")
    p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    if args.cmd == "seed":
        seed(args.market or [m.name for m in MARKETS])
    elif args.cmd == "enrich":
        enrich()
    elif args.cmd == "outage":
        outage(args.action)
    elif args.cmd == "weather":
        weather(args.action)
    else:
        export(args.out)


if __name__ == "__main__":
    main()
