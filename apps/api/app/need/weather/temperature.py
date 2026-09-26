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

from app.need.percentile import percentile_rank

# Scored thresholds (°C) and context thresholds.
HEAT_100F, HEAT_95F = 37.78, 35.0
COLD_28F, COLD_32F = -2.22, 0.0
LIMITATION = "Dry-bulb temperature only: no humidity or heat index."


def county_temperature_features(paths: list[Path], window_years: int = 5) -> pd.DataFrame:
    """Per Texas county: days >= 100°F / >= 95°F and <= 28°F / <= 32°F over 5 years and 365
    days ending at Data Through (last date in the data), Texas percentiles of the scored
    counts, and Temperature Extremes Exposure = their mean."""
    with duckdb.connect() as con:
        daily = con.execute(
            """SELECT fips, CAST(date AS DATE) AS day,
                      CAST(tmax AS DOUBLE) AS tmax, CAST(tmin AS DOUBLE) AS tmin
               FROM read_parquet(?) WHERE postal_code = 'TX'""",
            [[str(p) for p in paths]],
        ).df()
    data_through = daily["day"].max().date()
    end = pd.Timestamp(data_through + timedelta(days=1))
    windows = {"5y": end - pd.DateOffset(years=window_years), "365d": end - pd.Timedelta(days=365)}

    features = pd.DataFrame(index=sorted(daily["fips"].unique()))
    for suffix, since in windows.items():
        d = daily[(daily["day"] >= since) & (daily["day"] < end)]
        by = d.groupby("fips")
        features[f"heat_days_100f_{suffix}"] = by["tmax"].apply(lambda s: (s >= HEAT_100F).sum())
        features[f"heat_days_95f_{suffix}"] = by["tmax"].apply(lambda s: (s >= HEAT_95F).sum())
        features[f"cold_days_28f_{suffix}"] = by["tmin"].apply(lambda s: (s <= COLD_28F).sum())
        features[f"cold_days_32f_{suffix}"] = by["tmin"].apply(lambda s: (s <= COLD_32F).sum())
    features = features.fillna(0).astype(int)
    features["heat_100f_pctl"] = percentile_rank(features["heat_days_100f_5y"].astype(float))
    features["cold_28f_pctl"] = percentile_rank(features["cold_days_28f_5y"].astype(float))
    features["temperature_exposure"] = features[["heat_100f_pctl", "cold_28f_pctl"]].mean(axis=1)
    features["data_through"] = data_through
    return features.rename_axis("county_fips").reset_index()
