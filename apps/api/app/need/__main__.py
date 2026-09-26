"""Need Engine CLI. Run from apps/api:

uv run python -m app.need seed                     # every Market (idempotent)
uv run python -m app.need seed --market harris
uv run python -m app.need export cells.csv         # h3_index, resolution, center (for ML)
"""

import argparse
import csv
from pathlib import Path

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Cell
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
    p = sub.add_parser("export", help="write all Cells to CSV")
    p.add_argument("out", type=Path)
    args = parser.parse_args()

    if args.cmd == "seed":
        seed(args.market or [m.name for m in MARKETS])
    else:
        export(args.out)


if __name__ == "__main__":
    main()
