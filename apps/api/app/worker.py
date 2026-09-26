"""Weekly refresh loop, run by the docker-compose `worker` service:

    python -m app.worker          # sleep until the next scheduled run, forever
    python -m app.worker --now    # run once immediately, then exit

Each week: ERCOT prices (current-year files) -> grid scores, then every lead source ->
lead scores. Every source run is logged in source_runs (see /sources).
"""

import argparse
import time
import traceback
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.grid.__main__ import backfill, compute
from app.leads.__main__ import refresh, score
from app.leads.pipeline import SOURCES

TZ = ZoneInfo("America/Chicago")
RUN_WEEKDAY = 6  # Sunday
RUN_HOUR = 3  # 03:00 local, after most weekly upstream publications


def next_run(now: datetime) -> datetime:
    local = now.astimezone(TZ)
    candidate = local.replace(hour=RUN_HOUR, minute=0, second=0, microsecond=0)
    candidate += timedelta(days=(RUN_WEEKDAY - local.weekday()) % 7)
    if candidate <= local:
        candidate += timedelta(days=7)
    return candidate


def run_weekly() -> None:
    steps = [
        ("grid prices", lambda: backfill([datetime.now(TZ).year])),
        ("grid scores", compute),
        ("lead sources", lambda: refresh(list(SOURCES), force=False)),
        ("lead scores", score),
    ]
    for name, step in steps:
        print(f"[{datetime.now(UTC):%Y-%m-%d %H:%M}Z] {name}…", flush=True)
        try:
            step()
        except Exception:  # keep going: later steps can still use the data they have
            traceback.print_exc()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.worker")
    parser.add_argument("--now", action="store_true", help="run once now and exit")
    if parser.parse_args().now:
        run_weekly()
        return
    while True:
        when = next_run(datetime.now(UTC))
        print(f"Next weekly refresh: {when:%a %Y-%m-%d %H:%M %Z}", flush=True)
        time.sleep(max(0.0, (when - datetime.now(UTC)).total_seconds()))
        run_weekly()


if __name__ == "__main__":
    main()
