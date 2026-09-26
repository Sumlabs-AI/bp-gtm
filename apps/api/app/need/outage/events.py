"""Outage Events: continuous periods when a meaningful share of a county is without power.

Input is one county's EAGLE-I series (15-minute samples; rows exist only while someone is
out, so missing rows mean "no outage" or "not collected", indistinguishably). Durations are
county-level ("some customers in the county were out"), never one customer's outage.
"""

from datetime import timedelta

import pandas as pd
from pydantic import BaseModel

SAMPLE = pd.Timedelta(minutes=15)
COLUMNS = ["start", "end", "samples", "peak_customers_out", "customer_hours", "major"]


class EventRules(BaseModel):
    # A sample counts when at least this share of the county's customers are out.
    threshold_share: float = 0.001
    # Gaps shorter than this between counting samples are merged (missing/noisy data).
    merge_gap: timedelta = timedelta(hours=1)
    # Major Outage Event: peak share out, or customer-hours per customer, at or above these.
    major_peak_share: float = 0.05
    major_hours_per_customer: float = 1.0


def detect_events(series: pd.DataFrame, customers: int, rules: EventRules) -> pd.DataFrame:
    """Outage Events in a `ts`, `customers_out` series, one row per event (COLUMNS).

    Samples above the county's customer count are dropped as anomalous; events made of a
    single sample are ignored as spikes. Each sample stands for 15 minutes.
    """
    valid = series[series["customers_out"] <= customers]
    counting = valid[valid["customers_out"] >= rules.threshold_share * customers]
    counting = counting.sort_values("ts")
    if counting.empty:
        return pd.DataFrame(columns=COLUMNS)

    missing = counting["ts"].diff() - SAMPLE
    event_id = (missing >= rules.merge_gap).cumsum()
    events = counting.groupby(event_id).agg(
        start=("ts", "min"),
        end=("ts", "max"),
        samples=("ts", "size"),
        peak_customers_out=("customers_out", "max"),
        customer_hours=("customers_out", "sum"),
    )
    events = events[events["samples"] > 1].reset_index(drop=True)
    events["end"] = events["end"] + SAMPLE
    events["customer_hours"] = events["customer_hours"] * (SAMPLE / pd.Timedelta(hours=1))
    events["major"] = (events["peak_customers_out"] >= rules.major_peak_share * customers) | (
        events["customer_hours"] >= rules.major_hours_per_customer * customers
    )
    return events[COLUMNS]
