"""Refresh loop, run by the docker-compose `worker` service:

    python -m app.worker          # run jobs when due, forever
    python -m app.worker --now    # run the weekly job once immediately, then exit

Each week: ERCOT prices (current-year files) -> grid scores, then every lead source ->
lead scores. Every source run is logged in source_runs (see /sources).
Every few minutes: one NWS alert Snapshot (NWS Alerts, logged in nws_alert_snapshots).
Hourly: a forecast run (Forecast Signals, logged in forecast_runs). Failures never stop the
loop and never erase the last good data.
"""

import argparse
import threading
import time
import traceback
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.grid.__main__ import backfill, compute
from app.leads.__main__ import refresh, score
from app.leads.pipeline import SOURCES
from app.need.__main__ import forecast_refresh, live
from app.need.config import forecast, nws_alerts

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


def run_alerts() -> None:
    try:
        live("refresh")
    except Exception:  # never stop the loop; the next Snapshot retries
        traceback.print_exc()


def run_forecast() -> None:
    try:
        forecast_refresh()
    except Exception:  # never stop the loop; points keep their last good forecast
        traceback.print_exc()


def plan(now: datetime, next_at: dict[str, datetime]) -> tuple[list[str], datetime | None]:
    """Jobs due at `now` (in the given order), or when to wake up if none are."""
    due = [name for name, at in next_at.items() if at <= now]
    return due, None if due else min(next_at.values())


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.worker")
    parser.add_argument("--now", action="store_true", help="run the weekly job now and exit")
    if parser.parse_args().now:
        run_weekly()
        return
    start = datetime.now(UTC)
    # Quick live jobs first; the weekly job runs in its own thread.
    next_at = {"alerts": start, "forecast": start, "weekly": next_run(start)}
    every = {
        "alerts": timedelta(minutes=nws_alerts.refresh_minutes),
        "forecast": timedelta(minutes=forecast.refresh_minutes),
    }
    jobs = {"alerts": run_alerts, "forecast": run_forecast}
    weekly: threading.Thread | None = None
    print(f"Next weekly refresh: {next_at['weekly']:%a %Y-%m-%d %H:%M %Z}", flush=True)
    while True:
        due, wake = plan(datetime.now(UTC), next_at)
        for name in due:
            if name in jobs:
                jobs[name]()
                next_at[name] = datetime.now(UTC) + every[name]
        if "weekly" in due:
            # In its own thread: the weekly job can take hours, and live Snapshots must keep
            # coming meanwhile (or live data goes stale).
            if weekly is None or not weekly.is_alive():
                weekly = threading.Thread(target=run_weekly, name="weekly", daemon=True)
                weekly.start()
            next_at["weekly"] = next_run(datetime.now(UTC))
            print(f"Next weekly refresh: {next_at['weekly']:%a %Y-%m-%d %H:%M %Z}", flush=True)
        if wake:
            time.sleep(max(0.0, (wake - datetime.now(UTC)).total_seconds()))


if __name__ == "__main__":
    main()
