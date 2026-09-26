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


def test_plan_runs_due_jobs_and_sleeps_until_the_sooner_one():
    now = datetime(2026, 9, 26, 14, 0, tzinfo=TZ)
    weekly = datetime(2026, 9, 27, 3, 0, tzinfo=TZ)
    live = datetime(2026, 9, 26, 14, 0, tzinfo=TZ)
    assert plan(now, weekly, live) == (["live"], None)
    later = datetime(2026, 9, 26, 14, 5, tzinfo=TZ)
    assert plan(now, weekly, later) == ([], later)  # live refresh is sooner than weekly
    assert plan(weekly, weekly, weekly) == (["live", "weekly"], None)
