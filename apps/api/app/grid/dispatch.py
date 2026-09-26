"""Battery dispatch on real ERCOT prices: a realistic day-ahead planner and the
perfect-hindsight ceiling it is measured against.

Adapted from WattGap (https://github.com/saivarun3407/wattgap, MIT License, Copyright (c)
2026 Sai Varun; see LICENSE-wattgap): the planner from `dam_plan`/`planned` in
wattgap/econ.py and the ceiling from `perfect_foresight` in wattgap/locations.py.

Shared physics: charging and discharging each lose sqrt(round-trip efficiency); the
reserve share of capacity is never sold; wear is charged per kWh discharged; the battery
starts at its reserve and energy left at the end is worth nothing. Money is in $, energy
in kWh, prices in $/MWh.
"""

from math import ceil, sqrt

import numpy as np
import pandas as pd

from app.grid.config import BatteryConfig, PlannerConfig
from app.grid.sources import ERCOT_TZ

INTERVAL_H = 0.25  # real-time settlement interval


def usable_kwh(battery: BatteryConfig) -> float:
    return battery.capacity_kwh * (1 - battery.reserve_soc)


def window_hours(battery: BatteryConfig) -> tuple[int, int]:
    """Whole hours at full power to fill from the reserve (charge) and to empty back to it
    (discharge). WattGap sized its charge window this way; we size both, because its
    tuned 1-hour discharge window assumed a battery with more power per kWh than ours."""
    leg = sqrt(battery.round_trip_efficiency)
    usable = usable_kwh(battery)
    return (
        ceil(usable / leg / battery.power_kw - 1e-9),
        ceil(usable * leg / battery.power_kw - 1e-9),
    )


def day_plans(da: pd.Series, battery: BatteryConfig) -> pd.DataFrame:
    """Per day-ahead hour (UTC start): is it a planned charge or discharge hour, and the
    day's plan prices. Each local day uses only its own day-ahead prices, which ERCOT
    publishes the afternoon before, so the plan uses no hindsight."""
    charge_h, discharge_h = window_hours(battery)
    df = da.to_frame("dam")
    days = df.groupby(df.index.tz_convert(ERCOT_TZ).date)["dam"]
    rank, hours = days.rank(method="first"), days.transform("size")
    df["charge"] = rank <= charge_h
    df["discharge"] = rank > hours - discharge_h
    df["charge_cost"] = days.transform(lambda s: s.nsmallest(charge_h).mean())
    df["sell_price"] = days.transform(lambda s: s.nlargest(discharge_h).mean())
    df["top_dam"] = days.transform("max")
    # Lowest price at which selling beats the cost of the energy bought plus wear.
    df["breakeven"] = (
        df["charge_cost"].clip(lower=0) / battery.round_trip_efficiency
        + battery.wear_usd_per_kwh * 1000
    )
    # No plan when the day-ahead spread doesn't pay for losses and wear.
    df.loc[df["sell_price"] < df["breakeven"], ["charge", "discharge"]] = False
    return df


def simulate(
    rt: pd.Series, da: pd.Series, battery: BatteryConfig, planner: PlannerConfig
) -> pd.Series:
    """Net $ per local day (energy cash minus wear) of the day-ahead planner.

    - In the day's most expensive day-ahead hours it sells, spreading what's stored over
      the rest of the window, unless real time came in below breakeven.
    - In the cheapest hours it charges at full power if real time is cheap enough to pay
      back after losses and wear.
    - Outside the plan it sells at full power only when real time beats the day's top
      day-ahead price by `planner.spike_multiple`.
    Real-time prices are read only at the current interval.
    """
    plans = day_plans(da, battery).reindex(rt.index.floor("h"))
    local_day = rt.index.tz_convert(ERCOT_TZ).date
    discharge = plans["discharge"].fillna(False).astype(bool).to_numpy()
    # Intervals left in today's discharge window, this one included.
    left = (
        pd.Series(discharge[::-1].astype(int), index=local_day[::-1])
        .groupby(level=0)
        .cumsum()
        .to_numpy()[::-1]
    )
    sell_floor = plans["breakeven"].to_numpy()
    charge_ceiling = (
        plans["sell_price"] * battery.round_trip_efficiency - battery.wear_usd_per_kwh * 1000
    ).to_numpy()
    spike_bar = (
        planner.spike_multiple * np.maximum(plans["top_dam"], plans["breakeven"])
    ).to_numpy()

    leg, wear = sqrt(battery.round_trip_efficiency), battery.wear_usd_per_kwh
    usable, step = usable_kwh(battery), battery.power_kw * INTERVAL_H
    soc = 0.0  # kWh stored above the reserve
    cash = np.zeros(len(rt))
    rows = zip(
        rt.tolist(),
        discharge.tolist(),
        plans["charge"].fillna(False).astype(bool).tolist(),
        left.tolist(),
        sell_floor.tolist(),
        charge_ceiling.tolist(),
        spike_bar.tolist(),
        strict=True,
    )
    for i, (price, dis, chg, n_left, floor, ceiling, spike) in enumerate(rows):
        if dis:
            if price < floor:
                continue
            grid = min(step, soc * leg / n_left)  # kWh delivered
        elif chg:
            if price <= ceiling:
                grid = -min(step, (usable - soc) / leg)  # kWh drawn
            else:
                continue
        elif price >= spike:  # False when the day has no day-ahead prices (NaN)
            grid = min(step, soc * leg)
        else:
            continue
        if grid > 0:
            soc -= grid / leg
            cash[i] = grid * (price / 1000 - wear)
        else:
            soc -= grid * leg
            cash[i] = grid * price / 1000
    daily = pd.Series(cash, index=rt.index).groupby(local_day).sum()
    daily.index = pd.to_datetime(daily.index)
    return daily


def ceiling(rt: pd.Series, battery: BatteryConfig) -> float:
    """Most any battery with this physics could have earned knowing every price in
    advance ($): one linear program over the whole series (HiGHS).

    Variables per interval: kWh drawn c, kWh delivered d, kWh stored s. Simultaneous
    charge and discharge isn't ruled out (an LP can't); it only pays at negative prices,
    and it only loosens the bound.
    """
    from scipy.optimize import linprog
    from scipy.sparse import diags, eye, hstack

    n, leg = len(rt), sqrt(battery.round_trip_efficiency)
    if n == 0:
        return 0.0
    p = rt.to_numpy(dtype=float) / 1000  # $/kWh
    step = battery.power_kw * INTERVAL_H
    objective = np.concatenate([p, -(p - battery.wear_usd_per_kwh), np.zeros(n)])  # minimize
    # s_t - s_{t-1} - leg*c_t + d_t/leg = 0, starting empty (s_{-1} = 0)
    a = hstack([-leg * eye(n), eye(n) / leg, eye(n) - diags([np.ones(n - 1)], [-1])], format="csr")
    bounds = [(0, step)] * (2 * n) + [(0, usable_kwh(battery))] * n
    result = linprog(objective, A_eq=a, b_eq=np.zeros(n), bounds=bounds, method="highs")
    if result.status != 0:
        raise RuntimeError(result.message)
    return float(-result.fun)
