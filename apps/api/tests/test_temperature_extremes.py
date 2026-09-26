"""Temperature Extremes Exposure: measured hot/cold days per Texas county (nClimGrid)."""

import math
from datetime import date

import duckdb
import pandas as pd
import pytest

from app.need.weather.temperature import county_temperature_features


def day(fips, when, tmax, tmin, state="TX"):
    return {
        "region_type": "cty",
        "fips": fips,
        "postal_code": state,
        "date": pd.Timestamp(when),
        "tmax": f"{tmax:.2f}",
        "tmin": f"{tmin:.2f}",
        "tavg": "0",
        "prcp": "0",
    }


@pytest.fixture
def parquet(tmp_path):
    rows = [
        # Hot county: 3 days >= 100F (37.78C) incl. the exact boundary, one 96F day.
        day("48001", "2025-07-01", 38.5, 25),
        day("48001", "2025-07-02", 37.78, 25),
        day("48001", "2021-08-01", 40.0, 26),
        day("48001", "2025-07-03", 35.6, 24),
        day("48001", "2020-08-01", 45.0, 30),  # before the 5-year window
        # Cold county: 2 days <= 28F (-2.22C) incl. boundary, one 31F day.
        day("48003", "2025-01-10", 10, -2.22),
        day("48003", "2022-01-10", 8, -8.0),
        day("48003", "2025-01-11", 12, -0.5),
        # Mild county, and a non-Texas row that must be ignored.
        day("48005", "2025-12-31", 20, 5),
        day("22001", "2025-07-01", 45, 30, state="LA"),
    ]
    path = tmp_path / "202512.parquet"
    duckdb.from_df(pd.DataFrame(rows)).write_parquet(str(path))
    return [path]


def test_counts_measured_days_against_the_thresholds(parquet):
    f = county_temperature_features(parquet).set_index("county_fips")
    assert f.loc["48001", "data_through"] == date(2025, 12, 31)
    assert f.loc["48001", "heat_days_100f_5y"] == 3
    assert f.loc["48001", "heat_days_95f_5y"] == 4  # context only
    assert f.loc["48001", "heat_days_100f_365d"] == 2
    assert f.loc["48003", "cold_days_28f_5y"] == 2
    assert f.loc["48003", "cold_days_32f_5y"] == 3  # context only
    assert "22001" not in f.index


def test_exposure_is_mean_of_heat_and_cold_percentiles(parquet):
    f = county_temperature_features(parquet).set_index("county_fips")
    # heat 5y: 48001=3, 48003=0, 48005=0 -> 83.3, 33.3, 33.3; cold: 0, 2, 0 -> 33.3, 83.3, 33.3
    assert f.loc["48001", "heat_100f_pctl"] == pytest.approx(500 / 6)
    assert f.loc["48001", "temperature_exposure"] == pytest.approx((500 / 6 + 200 / 6) / 2)
    assert f.loc["48001", "temperature_exposure"] == pytest.approx(
        f.loc["48003", "temperature_exposure"]
    )
    assert f.loc["48005", "temperature_exposure"] < f.loc["48001", "temperature_exposure"]
    assert not any(math.isnan(v) for v in f["temperature_exposure"])
