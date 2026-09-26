"""Temperature Extremes Exposure: measured days of dangerous heat or cold per Texas county.

Source: NOAA nClimGrid-daily aggregated to counties (EpiNOAA, public domain, °C). Measured
temperature, not NWS advisories: across Texas, advisory days don't track measured extremes
(Spearman -0.29 heat, -0.07 cold) and are 70-85% explained by the issuing office.
Limitation: dry-bulb only, no humidity or heat index.
"""

from datetime import timedelta
from pathlib import Path

import duckdb
import pandas as pd

from app.need.config import WeatherConfig
from app.need.percentile import percentile_rank


def _celsius(fahrenheit: float) -> float:
    return (fahrenheit - 32) * 5 / 9


def county_temperature_features(
    paths: list[Path], config: WeatherConfig | None = None
) -> pd.DataFrame:
    """Per Texas county: days at or past the scored (100°F / 28°F) and context (95°F / 32°F)
    thresholds over 5 years and 365 days ending at Data Through (last date in the data),
    Texas percentiles of the scored counts, and Temperature Extremes Exposure = their mean.

    Files are named `<yyyymm>-<scaled|prelim>.parquet`; where a day exists in both, the final
    "scaled" value wins."""
    config = config or WeatherConfig()
    with duckdb.connect() as con:
        daily = con.execute(
            """SELECT fips, region_name, day, tmax, tmin FROM (
                   SELECT fips, region_name, CAST(date AS DATE) AS day,
                          CAST(tmax AS DOUBLE) AS tmax, CAST(tmin AS DOUBLE) AS tmin,
                          row_number() OVER (
                              PARTITION BY fips, CAST(date AS DATE)
                              ORDER BY contains(filename, '-scaled') DESC
                          ) AS pick
                   FROM read_parquet(?, filename = true) WHERE postal_code = 'TX')
               WHERE pick = 1""",
            [[str(p) for p in paths]],
        ).df()
    data_through = daily["day"].max().date()
    end = pd.Timestamp(data_through + timedelta(days=1))
    windows = {
        "5y": end - pd.DateOffset(years=config.window_years),
        "365d": end - pd.Timedelta(days=365),
    }
    thresholds = {
        "heat_days_100f": ("tmax", _celsius(config.heat_f), "ge"),
        "heat_days_95f": ("tmax", _celsius(config.heat_context_f), "ge"),
        "cold_days_28f": ("tmin", _celsius(config.cold_f), "le"),
        "cold_days_32f": ("tmin", _celsius(config.cold_context_f), "le"),
    }

    features = pd.DataFrame(index=pd.Index(sorted(daily["fips"].unique()), name="county_fips"))
    for suffix, since in windows.items():
        d = daily[(daily["day"] >= since) & (daily["day"] < end)]
        for name, (column, limit, op) in thresholds.items():
            hit = d[column] >= limit if op == "ge" else d[column] <= limit
            features[f"{name}_{suffix}"] = hit.groupby(d["fips"]).sum()
    features = features.fillna(0).astype(int)
    names = daily.drop_duplicates("fips").set_index("fips")["region_name"]
    features["county_name"] = names.str.replace(r"^TX: | County$", "", regex=True)
    features["heat_100f_pctl"] = percentile_rank(features["heat_days_100f_5y"].astype(float))
    features["cold_28f_pctl"] = percentile_rank(features["cold_days_28f_5y"].astype(float))
    features["temperature_exposure"] = features[["heat_100f_pctl", "cold_28f_pctl"]].mean(axis=1)
    features["data_through"] = data_through
    return features.reset_index()
