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
uv run python -m app.need live refresh            # one NWS alert Snapshot (worker: every 5 min)
uv run python -m app.need live forecast           # Forecast Signals for all points (worker: hourly)
uv run python -m app.need live grid               # ERCOT condition + reserves (worker: 5 min)
uv run python -m app.need live grid-prices        # RT zone prices from MIS (worker: 15 min)
uv run python -m app.need live grid-dam           # day-ahead zone prices from MIS (worker: hourly)
uv run python -m app.need baseline compute        # Baseline Need (after outage + weather)
uv run python -m app.need export-ml --out-dir data/ml         # need_features + res-6 reference
uv run python -m app.need import-propensity propensity.parquet  # the ML workstream's predictions
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


def live(action: str) -> None:
    from datetime import UTC, datetime

    from app.need.live import nws
    from app.need.live.alerts import take_snapshot

    if action == "forecast":
        forecast_refresh()
        return
    if action in ("grid", "grid-prices", "grid-dam"):
        grid_refresh(action)
        return

    with nws.client() as http, SessionLocal() as db:
        snapshot = take_snapshot(
            db,
            fetch=lambda: nws.fetch_alerts(http),
            resolve_zones=nws.zone_resolver(http),
            now=datetime.now(UTC),
        )
        db.commit()
    if snapshot.succeeded:
        print(
            f"NWS alert Snapshot {snapshot.fetched_at:%Y-%m-%d %H:%M}Z: "
            f"{snapshot.alerts_total} NWS alerts, {snapshot.signals_kept} kept as signals, "
            f"{snapshot.superseded} superseded",
            flush=True,
        )
    else:
        print(f"NWS alert Snapshot FAILED (signals unchanged): {snapshot.error}", flush=True)


def forecast_refresh() -> None:
    from datetime import UTC, datetime

    from app.need.config import forecast as config
    from app.need.live import nws
    from app.need.live.forecast_store import take_forecast_run

    with nws.client() as http, SessionLocal() as db:
        run = take_forecast_run(
            db,
            fetch_grid=lambda p: nws.fetch_gridpoint(http, p.office, p.grid_x, p.grid_y),
            fetch_spc=lambda: nws.fetch_spc_outlooks(http, config.spc_urls),
            now=datetime.now(UTC),
            lookup=lambda lat, lng: nws.grid_cell(http, lat, lng),
        )
        db.commit()
    seconds = (run.finished_at - run.started_at).total_seconds()
    print(
        f"Forecast run {run.started_at:%Y-%m-%d %H:%M}Z ({seconds:.0f}s): {run.points_ok} points "
        f"ok, {run.points_failed} failed, {len(run.point_errors)} errors; "
        f"SPC {'ok' if run.spc_ok else 'FAILED: ' + (run.spc_error or '')}",
        flush=True,
    )


def grid_refresh(action: str) -> None:
    """grid: poll ERCOT dashboards; grid-prices: RT prices; grid-dam: day-ahead prices."""
    from datetime import UTC, datetime

    from app.grid.sources import fetch_mis_recent
    from app.need.live import ercot
    from app.need.live.grid import refresh_prices, take_grid_poll

    if action == "grid":
        with SessionLocal() as db:
            row = take_grid_poll(db, ercot.fetch_dashboards, datetime.now(UTC))
            db.commit()
        if row.succeeded:
            print(
                f"ERCOT condition {row.fetched_at:%H:%M}Z: {row.title} (EEA {row.eea_level}), "
                f"PRC {row.prc_mw:,} MW, tightest forecast margin "
                f"{row.margin_forecast_min_mw or 0:,} MW",
                flush=True,
            )
        else:
            print(f"ERCOT condition poll FAILED (nothing changed): {row.error}", flush=True)
        return
    market = "RT" if action == "grid-prices" else "DA"
    print(
        f"ERCOT {market} prices: {refresh_prices(market, fetch_mis_recent):,} rows upserted",
        flush=True,
    )


def baseline() -> None:
    import pandas as pd

    from app.db import engine
    from app.need.baseline import compute_baseline
    from app.need.weather.pipeline import county_of_cells

    started = time.perf_counter()
    with SessionLocal() as db:
        report = compute_baseline(db, county_of_cells)
        db.commit()
    cells = pd.read_sql(
        "SELECT c.county_fips, b.baseline_need, b.raw, b.outage_input, b.weather_input, "
        "b.dominant_driver FROM cell_baseline_needs b JOIN cells c USING (h3_index)",
        engine,
    )
    print(
        f"Baseline Need\n{'─' * 30}\n"
        f"{'Reference res-6 cells:':<26}{report.reference_cells:>10,}\n"
        f"{'  ranked:':<26}{report.reference_ranked:>10,}\n"
        f"{'  outside any county:':<26}{report.reference_without_county:>10,} (not ranked)\n"
        f"{'  weather only (no O):':<26}{report.reference_without_outage:>10,}\n"
        f"{'Cells scored:':<26}{report.cells_scored:>10,} of {report.cells:,}\n"
        f"{'Duration:':<26}{time.perf_counter() - started:>9.1f}s\n"
    )
    raw = pd.read_sql("SELECT raw FROM baseline_need_references WHERE raw IS NOT NULL", engine)
    quantiles = raw["raw"].quantile([0.1, 0.25, 0.5, 0.75, 0.9]).round(1)
    print(
        "Reference raw quantiles: "
        + ", ".join(f"p{int(q * 100)} {v}" for q, v in quantiles.items())
    )
    summary = cells.groupby("county_fips").agg(
        cells=("baseline_need", "size"),
        baseline_min=("baseline_need", "min"),
        baseline_median=("baseline_need", "median"),
        baseline_max=("baseline_need", "max"),
        outage=("outage_input", "first"),
        weather_median=("weather_input", "median"),
    )
    print(summary.round(1).to_string())
    print("\nDominant driver:", cells["dominant_driver"].value_counts().to_dict())


def export_ml(out_dir: Path) -> None:
    from app.need.ml import export_features

    r = export_features(out_dir)
    print(
        f"ML export (feature_version {r.feature_version})\n{'─' * 30}\n"
        f"{r.features_path.name:<32}{r.cells:>8,} rows (res-8 product Cells)\n"
        f"{r.reference_path.name:<32}{r.reference_cells:>8,} rows (res-6 Texas reference)\n"
        f"columns: {', '.join(r.feature_columns)}\n"
        f"reference columns: {', '.join(r.reference_columns)}"
    )


def import_propensity_file(path: Path) -> None:
    from app.need.ml import PropensityFileRejected, import_propensity

    if not path.is_file():
        raise SystemExit(f"No such file: {path}")
    try:
        with SessionLocal() as db:
            r = import_propensity(db, path)
            db.commit()
    except PropensityFileRejected as exc:
        raise SystemExit(f"Rejected {path.name}: {exc}") from None
    print(
        f"Imported {path.name}: {r.rows:,} predictions ({r.product_cells:,} product Cells, "
        f"{r.other_cells:,} other Cells); model {', '.join(r.model_versions)}; "
        f"feature_version {', '.join(r.feature_versions)}"
    )
    for w in r.warnings:
        print(f"  warning: {w}")


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
    p = sub.add_parser("live", help="live signals: NWS alerts (and forecast signals)")
    p.add_argument("action", choices=["refresh", "forecast", "grid", "grid-prices", "grid-dam"])
    p = sub.add_parser("baseline", help="Baseline Need (after outage + weather compute)")
    p.add_argument("action", choices=["compute"])
    p = sub.add_parser("export-ml", help="need_features + need_reference_res6 Parquet")
    p.add_argument("--out-dir", type=Path, required=True)
    p = sub.add_parser("import-propensity", help="load the ML workstream's propensity.parquet")
    p.add_argument("path", type=Path)
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
    elif args.cmd == "live":
        live(args.action)
    elif args.cmd == "baseline":
        baseline()
    elif args.cmd == "export-ml":
        export_ml(args.out_dir)
    elif args.cmd == "import-propensity":
        import_propensity_file(args.path)
    else:
        export(args.out)


if __name__ == "__main__":
    main()
