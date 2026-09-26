"""Storm Exposure: Warning-days under NWS severe thunderstorm (SV), tornado (TO) and
extreme wind (EW) warning polygons, on the statewide H3 res-6 grid (~36 km²).

Polygons come from the IEM warning archive (public domain). Warnings, not reports: we
checked that SV/TO/EW warning-days track SPC severe reports across Texas (Spearman 0.76),
unlike NWS heat/cold advisories, which mostly reflect office practice.
"""

from datetime import date, timedelta

import pandas as pd
from shapely.geometry.base import BaseGeometry

from app import geo
from app.need.percentile import percentile_rank

RESOLUTION = 6
PHENOMENA = {"SV": "severe_thunderstorm", "TO": "tornado", "EW": "extreme_wind"}
LOCAL_TZ = "America/Chicago"


def _cells(geometry: BaseGeometry) -> list[str]:
    cells = geo.polygon_to_cells(geometry.__geo_interface__, RESOLUTION)
    if cells:
        return sorted(cells)
    # Smaller than a res-6 cell's reach: fall back to the cell holding its centroid.
    c = geometry.centroid
    return [geo.latlng_to_cell(c.y, c.x, RESOLUTION)]


def _local_days(issued: pd.Timestamp, expired: pd.Timestamp | None) -> list:
    """Every local date the warning was in effect (a warning spanning midnight covers both)."""
    start = issued.tz_convert(LOCAL_TZ)
    end = expired.tz_convert(LOCAL_TZ) - pd.Timedelta(minutes=1) if pd.notna(expired) else start
    return [d.date() for d in pd.date_range(start.normalize(), max(start, end).normalize())]


def warning_cells(warnings: pd.DataFrame) -> pd.DataFrame:
    """One row per (warning, res-6 cell, local day in effect): h3_index, day, phenom, wfo and
    the warning's identity (wfo, phenom, etn, year). Only SV/TO/EW polygon warnings count."""
    kept = warnings[
        warnings["phenom"].isin(PHENOMENA.keys())
        & (warnings["sig"] == "W")
        & (warnings["gtype"] == "P")
    ]
    rows = [
        {
            "h3_index": cell,
            "day": day,
            "phenom": w.phenom,
            "wfo": w.wfo,
            "warning": (w.wfo, w.phenom, w.etn, w.issued.year),
        }
        for w in kept.itertuples()
        for day in _local_days(w.issued, w.expired)
        for cell in _cells(w.geometry)
    ]
    return pd.DataFrame(rows, columns=["h3_index", "day", "phenom", "wfo", "warning"])


def storm_features(
    hits: pd.DataFrame, grid: list[str], data_through: date, window_years: int = 5
) -> pd.DataFrame:
    """Per res-6 cell of `grid` (the Reference Population): warning-days over 5 years and
    365 days ending at Data Through, distinct warnings by type, and Storm Exposure = Texas
    percentile of 5-year warning-days. Cells without warnings have 0 (a real zero)."""
    end = data_through + timedelta(days=1)
    since_5y = (pd.Timestamp(end) - pd.DateOffset(years=window_years)).date()
    since_365d = end - timedelta(days=365)
    in_window = hits[(hits["day"] >= since_5y) & (hits["day"] < end)]

    features = pd.DataFrame({"h3_index": grid}).set_index("h3_index")
    features["warning_days_5y"] = in_window.groupby("h3_index")["day"].nunique()
    recent = in_window[in_window["day"] >= since_365d]
    features["warning_days_365d"] = recent.groupby("h3_index")["day"].nunique()
    for code, name in PHENOMENA.items():
        of_type = in_window[in_window["phenom"] == code]
        features[f"{name}_warnings_5y"] = of_type.groupby("h3_index")["warning"].nunique()
    features = features.fillna(0).astype(int)
    # The office that issued most of the cell's warnings (for issuance-practice notes).
    warnings = in_window.drop_duplicates(["h3_index", "warning"])
    office = warnings.groupby("h3_index")["wfo"].agg(lambda s: s.value_counts().index[0])
    features["issuing_office"] = office.reindex(features.index).astype(object)
    features["issuing_office"] = features["issuing_office"].where(
        features["issuing_office"].notna(), None
    )
    features["storm_exposure"] = percentile_rank(features["warning_days_5y"].astype(float))
    features["resolution"] = RESOLUTION
    features["data_through"] = data_through
    return features.reset_index()
