import numpy as np
import pandas as pd
import pytest

from app.grid.config import BatteryConfig, PlannerConfig
from app.grid.dispatch import ceiling, simulate, window_hours

PLANNER = PlannerConfig()
# 4 kWh / 4 kW, lossless, no wear or reserve: 1-hour windows, 1 kWh per interval.
SIMPLE = BatteryConfig(
    capacity_kwh=4, power_kw=4, round_trip_efficiency=1.0, wear_usd_per_kwh=0, reserve_soc=0
)


def prices(hourly: list[list[float]], rt_hourly: list[list[float]] | None = None):
    """(rt, da) for consecutive local days from 24 day-ahead prices per day; real time
    repeats each hour's price over its four intervals unless given separately."""
    start = pd.Timestamp("2026-06-01", tz="America/Chicago")
    da_index = pd.date_range(start, periods=24 * len(hourly), freq="1h").tz_convert("UTC")
    da = pd.Series(np.concatenate(hourly), index=da_index, dtype=float)
    rt_index = pd.date_range(start, periods=96 * len(hourly), freq="15min").tz_convert("UTC")
    rt = pd.Series(np.repeat(np.concatenate(rt_hourly or hourly), 4), index=rt_index, dtype=float)
    return rt, da


def day(cheap_hour=2, cheap=10.0, peak_hour=19, peak=110.0, base=50.0) -> list[float]:
    hours = [base] * 24
    hours[cheap_hour], hours[peak_hour] = cheap, peak
    return hours


def test_window_hours_fit_the_battery():
    assert window_hours(SIMPLE) == (1, 1)
    # 20 kWh usable at 11.5 kW: ~1.9 h to fill through losses, ~1.6 h to empty.
    assert window_hours(BatteryConfig(capacity_kwh=25, power_kw=11.5)) == (2, 2)


def test_planner_charges_cheap_and_sells_the_peak():
    rt, da = prices([day()])
    # Buy 4 kWh at $10/MWh, sell 4 kWh at $110/MWh; hindsight can't do better.
    assert simulate(rt, da, SIMPLE, PLANNER).sum() == pytest.approx(0.40)
    assert ceiling(rt, SIMPLE) == pytest.approx(0.40)


def test_wear_and_reserve_cost_value():
    battery = SIMPLE.model_copy(
        update={"capacity_kwh": 5, "reserve_soc": 0.2, "wear_usd_per_kwh": 0.02}
    )
    rt, da = prices([day()])
    # Same 4 kWh usable, minus $0.02 wear on each kWh sold.
    assert simulate(rt, da, battery, PLANNER).sum() == pytest.approx(0.40 - 4 * 0.02)


def test_no_trade_when_the_spread_does_not_cover_losses():
    lossy = SIMPLE.model_copy(update={"round_trip_efficiency": 0.8})
    rt, da = prices([day(cheap=50, peak=55)])
    assert simulate(rt, da, lossy, PLANNER).sum() == 0


def test_holds_in_the_window_when_real_time_comes_in_cheap():
    plan = day()
    actual = day(peak=5)  # the evening peak never showed up in real time
    rt, da = prices([plan], [actual])
    # It charged at $10 and never sold below that breakeven.
    assert simulate(rt, da, SIMPLE, PLANNER).sum() == pytest.approx(-0.04)


def test_sells_into_a_real_time_spike_outside_the_plan():
    actual = day()
    actual[12] = 1000  # 1000 >= 1.25 × the $110 day-ahead top
    rt, da = prices([day()], [actual])
    assert simulate(rt, da, SIMPLE, PLANNER).sum() == pytest.approx(-0.04 + 4 * 1000 / 1000)


def test_uses_no_future_prices():
    rt, da = prices([day(), day()])
    later_rt, later_da = prices([day(), day(peak=900)], [day(), day(peak=5)])
    first = simulate(rt, da, SIMPLE, PLANNER)
    changed = simulate(later_rt, later_da, SIMPLE, PLANNER)
    assert changed.iloc[0] == first.iloc[0]
    assert changed.iloc[1] != first.iloc[1]


def test_planner_never_beats_the_ceiling():
    rng = np.random.default_rng(7)
    days = 40 + 30 * rng.standard_normal((5, 24))
    actual = days + 60 * rng.standard_normal((5, 24)) + 900 * (rng.random((5, 24)) < 0.03)
    rt, da = prices(list(days), list(actual))
    for battery in (
        SIMPLE,
        BatteryConfig(capacity_kwh=25, power_kw=11.5),
        BatteryConfig(capacity_kwh=50, power_kw=23),
    ):
        realistic = simulate(rt, da, battery, PLANNER).sum()
        assert realistic <= ceiling(rt, battery) + 1e-9
