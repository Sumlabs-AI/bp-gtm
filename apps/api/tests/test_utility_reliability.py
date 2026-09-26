"""Utility Reliability Need inputs from EIA-861 yearly rows, ranked against Texas utilities."""

import math

import pandas as pd
import pytest

from app.need.outage.eia import utility_reliability


def yearly(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=[
            "year",
            "utility_id",
            "utility_name",
            "ownership",
            "saidi_w_med",
            "saifi_w_med",
            "saidi_wo_med",
            "saifi_wo_med",
            "customers",
            "standard",
        ],
    )


DATA = yearly(
    [
        # CenterPoint-like: 5 years, one hurricane year (with MED) but steady without MED.
        *[
            (y, 1, "Big IOU", "Investor Owned", 200.0, 1.5, 150.0, 1.2, 2_600_000, "IEEE")
            for y in (2020, 2021, 2022, 2023)
        ],
        (2024, 1, "Big IOU", "Investor Owned", 4316.0, 3.0, 150.0, 1.2, 2_700_000, "IEEE"),
        # Muni: reliable.
        *[
            (y, 2, "City Utility", "Municipal", 80.0, 0.8, 60.0, 0.7, 500_000, "IEEE")
            for y in range(2020, 2025)
        ],
        # Co-op: only 2 years reported.
        (2023, 3, "Rural Coop", "Cooperative", 300.0, 2.0, 240.0, 1.8, 50_000, "Other"),
        (2024, 3, "Rural Coop", "Cooperative", 320.0, 2.1, 260.0, 1.9, 50_000, "Other"),
        # Reported with MED only: no SAIDI without MED -> outside the Reference Population.
        (2024, 4, "Partial", "Municipal", 90.0, 1.0, None, None, 10_000, "IEEE"),
    ]
)


def test_five_year_mean_without_major_events():
    result = utility_reliability(DATA, window_years=5).set_index("utility_id")
    assert result.loc[1, "saidi_wo_med_5y"] == 150.0  # the hurricane year doesn't move it
    assert result.loc[1, "saidi_w_med_5y"] == pytest.approx((4 * 200 + 4316) / 5)
    assert result.loc[1, "years_used"] == 5
    assert result.loc[1, "data_through_year"] == 2024


def test_fewer_years_are_used_and_counted():
    result = utility_reliability(DATA, window_years=5).set_index("utility_id")
    assert result.loc[3, "years_used"] == 2
    assert result.loc[3, "saidi_wo_med_5y"] == 250.0


def test_less_reliable_utilities_have_higher_need():
    result = utility_reliability(DATA, window_years=5).set_index("utility_id")
    assert (
        result.loc[3, "reliability_need"]
        > result.loc[1, "reliability_need"]
        > result.loc[2, "reliability_need"]
    )
    assert result.loc[3, "reliability_need"] == pytest.approx(500 / 6)
    assert math.isnan(result.loc[4, "reliability_need"])  # no SAIDI without MED: unknown
    assert result.loc[4, "saidi_w_med_5y"] == 90.0  # raw context kept


def test_only_the_last_window_years_count():
    older = pd.concat(
        [
            DATA,
            yearly(
                [(2015, 2, "City Utility", "Municipal", 999.0, 9.0, 999.0, 9.0, 500_000, "IEEE")]
            ),
        ]
    )
    result = utility_reliability(older, window_years=5).set_index("utility_id")
    assert result.loc[2, "saidi_wo_med_5y"] == 60.0
