"""Outage Events from a county's customer-out series (EAGLE-I, 15-minute samples)."""

import pandas as pd

from app.need.outage.events import EventRules, detect_events

CUSTOMERS = 100_000  # modeled customers in the county
RULES = EventRules()  # 0.1% threshold, 1 h merge, major at 5% peak or 1 h/customer


def series(*runs: tuple[str, int, int]) -> pd.DataFrame:
    """(start, samples, customers_out) runs of 15-minute samples; gaps are missing rows."""
    rows = []
    for start, n, out in runs:
        for ts in pd.date_range(start, periods=n, freq="15min", tz="UTC"):
            rows.append((ts, out))
    return pd.DataFrame(rows, columns=["ts", "customers_out"])


def test_a_sustained_outage_is_one_event():
    events = detect_events(series(("2024-07-08 06:00", 8, 500)), CUSTOMERS, RULES)
    assert len(events) == 1
    event = events.iloc[0]
    assert event.start == pd.Timestamp("2024-07-08 06:00", tz="UTC")
    assert event.end == pd.Timestamp("2024-07-08 08:00", tz="UTC")  # last sample + 15 min
    assert event.peak_customers_out == 500
    assert event.customer_hours == 8 * 0.25 * 500
    assert not event.major


def test_below_threshold_is_not_an_event():
    # 0.1% of 100k = 100 customers; 99 is routine noise.
    assert detect_events(series(("2024-01-01", 20, 99)), CUSTOMERS, RULES).empty


def test_short_gaps_merge_and_long_gaps_split():
    merged = series(("2024-01-01 00:00", 4, 200), ("2024-01-01 01:45", 4, 200))  # 45 min gap
    assert len(detect_events(merged, CUSTOMERS, RULES)) == 1

    split = series(("2024-01-01 00:00", 4, 200), ("2024-01-01 03:00", 4, 200))  # 2 h gap
    assert len(detect_events(split, CUSTOMERS, RULES)) == 2


def test_isolated_single_samples_are_ignored():
    spike = series(("2024-01-01 00:00", 1, 5_000))
    assert detect_events(spike, CUSTOMERS, RULES).empty


def test_samples_above_every_customer_are_ignored():
    # An anomalous 150% reading inside a real event neither splits it nor sets its peak.
    data = series(
        ("2024-01-01 00:00", 3, 300), ("2024-01-01 00:45", 1, 150_000), ("2024-01-01 01:00", 3, 300)
    )
    events = detect_events(data, CUSTOMERS, RULES)
    assert len(events) == 1
    assert events.iloc[0].peak_customers_out == 300


def test_major_by_peak_share():
    # 5% of customers out at the peak, briefly.
    events = detect_events(series(("2024-05-16 22:00", 2, 5_000)), CUSTOMERS, RULES)
    assert events.iloc[0].major


def test_major_by_customer_hours():
    # Never reaches 5%, but 4,000 out for 26 h = 104,000 customer-hours >= 1 per customer.
    events = detect_events(series(("2021-02-15 00:00", 104, 4_000)), CUSTOMERS, RULES)
    event = events.iloc[0]
    assert event.peak_customers_out / CUSTOMERS < 0.05
    assert event.major


def test_unsorted_input_and_no_rows():
    shuffled = series(("2024-01-01 00:00", 6, 500)).sample(frac=1, random_state=1)
    assert len(detect_events(shuffled, CUSTOMERS, RULES)) == 1
    assert detect_events(series(), CUSTOMERS, RULES).empty
