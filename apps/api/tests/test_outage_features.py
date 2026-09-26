"""County outage features from normalized EAGLE-I Parquet, ranked against Texas."""

import math
from datetime import date

import duckdb
import pandas as pd
import pytest

from app.need.outage.eaglei import county_features
from app.need.outage.events import EventRules

CUSTOMERS = {"48001": 10_000, "48003": 10_000, "48005": 10_000, "48007": 10_000}


def samples(fips: str, start: str, n: int, out: int) -> list[tuple]:
    return [
        (fips, f"County {fips}", ts, out)
        for ts in pd.date_range(start, periods=n, freq="15min", tz="UTC")
    ]


@pytest.fixture
def parquet(tmp_path):
    rows = []
    for year in range(2021, 2026):
        # Every year: a small routine event in all three regular counties (keeps them observed).
        for fips in ("48001", "48003", "48005"):
            rows += samples(fips, f"{year}-03-01", 4, 20)
    # 48001: a major storm in 2021 (outside 365 d, inside 5 y) and one in 2025 (inside both).
    rows += samples("48001", "2021-02-15", 40, 2_000)
    rows += samples("48001", "2025-07-08", 8, 1_000)
    # 48003: one major storm in 2023 only.
    rows += samples("48003", "2023-05-16", 8, 800)
    # 48007: only seen in 2025 -> not enough years for the Reference Population.
    rows += samples("48007", "2025-06-01", 8, 5_000)
    # The data ends here: Data Through is this date.
    rows += samples("48005", "2025-12-31 23:00", 2, 5)
    path = tmp_path / "eaglei_tx.parquet"
    frame = pd.DataFrame(rows, columns=["fips", "county", "ts", "customers_out"])
    duckdb.from_df(frame).write_parquet(str(path))
    return path


def test_windows_end_at_data_through(parquet):
    features = county_features(parquet, CUSTOMERS, EventRules()).set_index("county_fips")
    harris_like = features.loc["48001"]
    assert harris_like.data_through == date(2025, 12, 31)
    # 2025 storm (8 x 15 min x 1,000) + 2025 routine (4 x 15 min x 20); 2021 storm is out.
    assert harris_like.hours_per_customer_365d == pytest.approx((2_000 + 20) / 10_000)
    assert harris_like.major_outage_events_365d == 1
    assert harris_like.major_outage_events_5y == 2
    assert harris_like.outage_events_5y == 7  # 5 routine + 2 storms
    assert harris_like.peak_pct_out_5y == pytest.approx(0.2)
    assert harris_like.last_observed_major_outage_on == date(2025, 7, 8)


def test_percentiles_rank_the_reference_population_only(parquet):
    features = county_features(parquet, CUSTOMERS, EventRules()).set_index("county_fips")
    reference = features[features.in_reference]
    assert set(reference.index) == {"48001", "48003", "48005"}
    # 48001 has the most outage hours and major events: highest percentiles.
    assert features.loc["48001", "hours_per_customer_pctl"] == pytest.approx(500 / 6)
    # Observed Outage Exposure is that percentile alone; event counts don't move it.
    assert (
        (features["observed_exposure"] == features["hours_per_customer_pctl"])
        .loc[reference.index]
        .all()
    )
    assert features.loc["48001", "observed_exposure"] > features.loc["48003", "observed_exposure"]
    assert features.loc["48005", "major_outage_events_5y"] == 0

    sparse = features.loc["48007"]
    assert sparse.years_observed == 1 and not sparse.in_reference
    assert sparse.major_outage_events_5y == 1  # raw metrics kept...
    assert math.isnan(sparse.hours_per_customer_pctl)  # ...but no percentile
    assert math.isnan(sparse.observed_exposure)


def test_counties_without_any_data_are_unknown_not_zero(parquet):
    features = county_features(parquet, {**CUSTOMERS, "48009": 10_000}, EventRules())
    empty = features.set_index("county_fips").loc["48009"]
    assert empty.years_observed == 0
    assert math.isnan(empty.hours_per_customer_5y)
    assert empty.last_observed_major_outage_on is None
