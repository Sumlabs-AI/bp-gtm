"""Lead pipeline CLI. Run from apps/api (or `docker compose exec api python -m app.leads …`):

uv run python -m app.leads refresh                 # every source, skip unchanged ones
uv run python -m app.leads refresh hcad --force    # one source, even if unchanged
uv run python -m app.leads score                   # rebuild the scored leads
uv run python -m app.leads weekly                  # refresh all, then score
"""

import argparse
import sys
from datetime import UTC, datetime

from app.leads.config import scoring
from app.leads.pipeline import SOURCES, run_source
from app.leads.scoring import score_leads


def refresh(source_ids: list[str], force: bool) -> bool:
    ok = True
    for source_id in source_ids:
        run = run_source(source_id, force=force)
        detail = run.error.strip().splitlines()[-1] if run.error else ""
        print(
            f"{source_id}: {run.status} rows={run.rows} inserted={run.inserted} "
            f"updated={run.updated} {detail}",
            flush=True,
        )
        ok &= run.status != "failed"
    return ok


def score(baseline: bool = False) -> None:
    summary = score_leads(datetime.now(UTC), scoring, baseline=baseline)
    print(
        f"{summary['candidates']:,} single-family homesteads, {summary['eligible']:,} eligible, "
        f"{summary['new']:,} new this week"
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.leads")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("refresh", help="refresh data sources")
    p.add_argument("sources", nargs="*", help=f"default: all ({', '.join(SOURCES)})")
    p.add_argument("--force", action="store_true", help="reload even if unchanged")
    p = sub.add_parser("score", help="rebuild scored leads")
    p.add_argument(
        "--baseline",
        action="store_true",
        help="don't flag newly eligible homes as new (use after changing matching rules)",
    )
    sub.add_parser("weekly", help="refresh every source, then score")
    sub.add_parser("cells", help="backfill each located property's H3 Cell (h3_index)")
    args = parser.parse_args()

    if args.cmd == "cells":
        from app.leads.store import assign_cells

        print(f"{assign_cells():,} properties assigned their H3 Cell")
        return
    if args.cmd == "refresh":
        unknown = set(args.sources) - set(SOURCES)
        if unknown:
            parser.error(f"unknown source(s): {', '.join(sorted(unknown))}")
        ok = refresh(args.sources or list(SOURCES), args.force)
    elif args.cmd == "score":
        score(args.baseline)
        ok = True
    else:
        ok = refresh(list(SOURCES), force=False)
        score()  # score even if one source failed: the others may have news
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
