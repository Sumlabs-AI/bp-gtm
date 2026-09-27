"""Data snapshot: the computed product data, committed to the repo so a fresh clone runs with
real scores. `pnpm up` loads it when the database has no leads (the api container's command).

uv run python -m app.snapshot export      # write snapshot/ from this database
uv run python -m app.snapshot load        # load it if the database has no leads yet
uv run python -m app.snapshot load --force   # replace the snapshot tables' data

One gzipped CSV per table (large tables in parts, each well under GitHub's 100 MB file limit)
plus manifest.json (Alembic revision, row counts). Only what the product shows is exported:
leads and their homes, Cell scores, grid values. Not the ERCOT meters or raw grid prices
(inputs to re-scoring; rebuild them with the pipelines, see wiki/development.md), and not live
tables (the worker refills them). Owner names and mailing addresses are left out.
"""

import argparse
import gzip
import io
import json
import sys
import time
from pathlib import Path

from sqlalchemy import text

from app.db import engine

DIR = Path(__file__).resolve().parents[1] / "snapshot"
PART_ROWS = 300_000  # ~30 MB of gzipped leads per part

# Load order: parents before children (leads -> properties, cell_propensities -> imports).
TABLES: dict[str, str] = {
    "cells": "SELECT * FROM cells",
    "storm_features": "SELECT * FROM storm_features",
    "county_temperature_features": "SELECT * FROM county_temperature_features",
    "county_outage_features": "SELECT * FROM county_outage_features",
    "utility_reliability_features": "SELECT * FROM utility_reliability_features",
    "baseline_need_references": "SELECT * FROM baseline_need_references",
    "cell_baseline_needs": "SELECT * FROM cell_baseline_needs",
    "propensity_imports": "SELECT * FROM propensity_imports",
    "cell_propensities": "SELECT * FROM cell_propensities",
    "grid_zone_metrics": "SELECT * FROM grid_zone_metrics",
    # Only homes that are leads, without owner names or mailing addresses.
    "properties": "SELECT {columns} FROM properties WHERE id IN (SELECT property_id FROM leads)",
    "permits": "SELECT * FROM permits",
    "leads": "SELECT * FROM leads",
    "source_runs": "SELECT * FROM source_runs",
}
PRIVATE_COLUMNS = {"properties": {"owner_name", "mail_address"}}
KEYS = {"properties": "id", "leads": "property_id"}  # stable part order for big tables


def _columns(conn, table: str) -> list[str]:
    return list(
        conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t ORDER BY ordinal_position"
            ),
            {"t": table},
        ).scalars()
    )


def _revision(conn) -> str:
    return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def export(out: Path = DIR) -> None:
    out.mkdir(exist_ok=True)
    for old in out.glob("*.csv.gz"):
        old.unlink()
    manifest = {"tables": {}}
    with engine.connect() as conn:
        manifest["alembic_revision"] = _revision(conn)
        raw = conn.connection.dbapi_connection
        for table, query in TABLES.items():
            private = PRIVATE_COLUMNS.get(table, set())
            columns = ", ".join(
                f"NULL AS {c}" if c in private else c for c in _columns(conn, table)
            )
            query = query.format(columns=columns)
            if table in KEYS:
                query += f" ORDER BY {KEYS[table]}"
            total = conn.execute(text(f"SELECT count(*) FROM ({query}) q")).scalar_one()
            parts = []
            for n, offset in enumerate(range(0, max(total, 1), PART_ROWS)):
                name = f"{table}.csv.gz" if total <= PART_ROWS else f"{table}.{n}.csv.gz"
                page = f"{query} LIMIT {PART_ROWS} OFFSET {offset}" if total > PART_ROWS else query
                with raw.cursor() as cur, gzip.open(out / name, "wb", compresslevel=6) as f:
                    with cur.copy(f"COPY ({page}) TO STDOUT WITH (FORMAT csv, HEADER)") as copy:
                        for chunk in copy:
                            f.write(chunk)
                parts.append(name)
            manifest["tables"][table] = {"rows": total, "files": parts}
            size = sum((out / p).stat().st_size for p in parts) / 1e6
            print(f"{table:<30}{total:>10,} rows {size:>8.1f} MB")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def load(src: Path = DIR, force: bool = False) -> bool:
    """Load the snapshot. Without force, only into a database that has no leads. Returns
    whether data was loaded."""
    manifest_path = src / "manifest.json"
    if not manifest_path.exists():
        print("No data snapshot in the repo: skipping.")
        return False
    manifest = json.loads(manifest_path.read_text())
    started = time.perf_counter()
    with engine.begin() as conn:
        revision = _revision(conn)
        if revision != manifest["alembic_revision"]:
            print(
                f"Data snapshot is for schema {manifest['alembic_revision']}, database is at "
                f"{revision}: not loaded. Re-export it (python -m app.snapshot export)."
            )
            return False
        if not force and conn.execute(text("SELECT EXISTS (SELECT 1 FROM leads)")).scalar():
            print("Database already has leads: data snapshot not loaded (use --force).")
            return False
        print("Loading the data snapshot (first start, ~1-2 min)…", flush=True)
        tables = list(manifest["tables"])
        conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
        raw = conn.connection.dbapi_connection
        for table in tables:
            info = manifest["tables"][table]
            with raw.cursor() as cur:
                for name in info["files"]:
                    with gzip.open(src / name, "rb") as f:
                        header = io.TextIOWrapper(f, encoding="utf-8").readline().strip()
                    with (
                        gzip.open(src / name, "rb") as f,
                        cur.copy(
                            f"COPY {table} ({header}) FROM STDIN WITH (FORMAT csv, HEADER)"
                        ) as copy,
                    ):
                        while chunk := f.read(1 << 20):
                            copy.write(chunk)
            # Serial ids continue after the loaded rows.
            seq = (
                conn.execute(text("SELECT pg_get_serial_sequence(:t, 'id')"), {"t": table}).scalar()
                if "id" in _columns(conn, table)
                else None
            )
            if seq:
                conn.execute(
                    text(
                        f"SELECT setval(:s, COALESCE((SELECT max(id) FROM {table}), 0) + 1, false)"
                    ),
                    {"s": seq},
                )
            print(f"  {table:<30}{info['rows']:>10,} rows", flush=True)
    print(f"Data snapshot loaded in {time.perf_counter() - started:.0f}s.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.snapshot")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("export", help="write snapshot/ from this database")
    p = sub.add_parser("load", help="load snapshot/ if the database has no leads")
    p.add_argument("--force", action="store_true", help="replace the snapshot tables' data")
    args = parser.parse_args()
    if args.cmd == "export":
        export()
    else:
        load(force=args.force)
    sys.exit(0)


if __name__ == "__main__":
    main()
