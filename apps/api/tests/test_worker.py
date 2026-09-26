from datetime import datetime
from zoneinfo import ZoneInfo

from app.worker import next_run, plan

TZ = ZoneInfo("America/Chicago")


def test_next_run_is_the_coming_sunday_3am_local():
    friday = datetime(2026, 9, 25, 22, 0, tzinfo=TZ)
    assert next_run(friday) == datetime(2026, 9, 27, 3, 0, tzinfo=TZ)


def test_next_run_skips_to_next_week_once_passed():
    sunday_noon = datetime(2026, 9, 27, 12, 0, tzinfo=TZ)
    assert next_run(sunday_noon) == datetime(2026, 10, 4, 3, 0, tzinfo=TZ)
    sunday_2am = datetime(2026, 9, 27, 2, 0, tzinfo=TZ)
    assert next_run(sunday_2am) == datetime(2026, 9, 27, 3, 0, tzinfo=TZ)


def test_plan_runs_due_jobs_and_sleeps_until_the_soonest():
    now = datetime(2026, 9, 26, 14, 0, tzinfo=TZ)
    weekly = datetime(2026, 9, 27, 3, 0, tzinfo=TZ)
    soon = datetime(2026, 9, 26, 14, 5, tzinfo=TZ)
    hour = datetime(2026, 9, 26, 15, 0, tzinfo=TZ)
    assert plan(now, {"alerts": now, "forecast": hour, "weekly": weekly}) == (["alerts"], None)
    assert plan(now, {"alerts": soon, "forecast": hour, "weekly": weekly}) == ([], soon)
    everything = {"alerts": weekly, "forecast": weekly, "weekly": weekly}
    assert plan(weekly, everything) == (["alerts", "forecast", "weekly"], None)
