"""Refresh loop, run by the docker-compose `worker` service:

    python -m app.worker          # run jobs when due, forever
    python -m app.worker --now    # run the weekly job once immediately, then exit

Each week: ERCOT prices (current-year files) -> grid scores, then every lead source ->
lead scores. Every source run is logged in source_runs (see /sources).
Every few minutes: one NWS alert Snapshot for Live Weather Signals (logged in
live_weather_snapshots; a failure changes no signal).
"""

import argparse
import time
import traceback
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.grid.__main__ import backfill, compute
from app.leads.__main__ import refresh, score
from app.leads.pipeline import SOURCES
from app.need.__main__ import live
from app.need.config import live_weather

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


def run_live() -> None:
    try:
        live("refresh")
    except Exception:  # never stop the loop; the next Snapshot retries
        traceback.print_exc()


def plan(
    now: datetime, next_weekly: datetime, next_live: datetime
) -> tuple[list[str], datetime | None]:
    """Jobs due at `now` (live first: it's quick), or when to wake up if none are."""
    due = [name for name, at in (("live", next_live), ("weekly", next_weekly)) if at <= now]
    return due, None if due else min(next_weekly, next_live)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.worker")
    parser.add_argument("--now", action="store_true", help="run the weekly job now and exit")
    if parser.parse_args().now:
        run_weekly()
        return
    next_weekly = next_run(datetime.now(UTC))
    next_live = datetime.now(UTC)
    print(f"Next weekly refresh: {next_weekly:%a %Y-%m-%d %H:%M %Z}", flush=True)
    while True:
        due, wake = plan(datetime.now(UTC), next_weekly, next_live)
        if "live" in due:
            run_live()
            next_live = datetime.now(UTC) + timedelta(minutes=live_weather.refresh_minutes)
        if "weekly" in due:
            run_weekly()
            next_weekly = next_run(datetime.now(UTC))
            print(f"Next weekly refresh: {next_weekly:%a %Y-%m-%d %H:%M %Z}", flush=True)
        if wake:
            time.sleep(max(0.0, (wake - datetime.now(UTC)).total_seconds()))


if __name__ == "__main__":
    main()
