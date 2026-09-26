"""EIA Form 861 reliability (public domain): yearly SAIDI/SAIFI per utility and state.

SAIDI = interruption minutes for the average customer; SAIFI = interruptions per customer.
"Without MED" excludes major event days, i.e. normal-conditions reliability, which is what
Utility Reliability Need ranks. Utilities report under the IEEE standard or an "Other"
standard (e.g. Oncor); we take IEEE when present.
"""

import io
import zipfile
from pathlib import Path

import pandas as pd

from app.need.percentile import percentile_rank

ZIP_URL = "https://www.eia.gov/electricity/data/eia861/zip/f861{year}.zip"
ARCHIVE_URL = "https://www.eia.gov/electricity/data/eia861/archive/zip/f861{year}.zip"

# Column positions in Reliability_<year>.xlsx (stable 2020-2024; header row found by name).
IEEE = {"saidi_w_med": 5, "saifi_w_med": 6, "saidi_wo_med": 8, "saifi_wo_med": 9, "customers": 14}
OTHER = {
    "saidi_w_med": 17,
    "saifi_w_med": 18,
    "saidi_wo_med": 20,
    "saifi_wo_med": 21,
    "customers": 23,
}
METRICS = ["saidi_w_med", "saifi_w_med", "saidi_wo_med", "saifi_wo_med"]


def parse_reliability(zip_path: Path, state: str = "TX") -> pd.DataFrame:
    """One row per utility in `state` for the zip's year (see utility_reliability for columns)."""
    with zipfile.ZipFile(zip_path) as z:
        name = next(n for n in z.namelist() if n.startswith("Reliability_"))
        raw = pd.read_excel(io.BytesIO(z.read(name)), header=None)
    header = raw.index[raw.apply(lambda r: "Utility Number" in r.astype(str).tolist(), axis=1)][0]
    rows = raw.iloc[header + 1 :]
    rows = rows[rows[3] == state]

    def block(columns: dict[str, int]) -> pd.DataFrame:
        return (
            rows[list(columns.values())]
            .set_axis(list(columns), axis=1)
            .apply(pd.to_numeric, errors="coerce")
        )

    ieee, other = block(IEEE), block(OTHER)
    use_ieee = ieee[METRICS].notna().any(axis=1)
    values = ieee.where(use_ieee, other, axis=0)
    return pd.DataFrame(
        {
            "year": pd.to_numeric(rows[0]).astype(int),
            "utility_id": pd.to_numeric(rows[1]).astype(int),
            "utility_name": rows[2],
            "ownership": rows[4],
            **{c: values[c] for c in [*METRICS, "customers"]},
            "standard": use_ieee.map({True: "IEEE", False: "Other"}),
        }
    ).reset_index(drop=True)


def utility_reliability(yearly: pd.DataFrame, window_years: int = 5) -> pd.DataFrame:
    """Per utility: means over the last `window_years` years present in the data (fewer if a
    utility reported fewer, counted in years_used), and Utility Reliability Need = Texas
    percentile of mean SAIDI without MED (null when a utility never reported it)."""
    last = int(yearly["year"].max())
    recent = yearly[yearly["year"] > last - window_years]
    grouped = recent.sort_values("year").groupby("utility_id")
    result = grouped.agg(
        utility_name=("utility_name", "last"),
        ownership=("ownership", "last"),
        customers=("customers", "last"),
        **{f"{m}_5y": (m, "mean") for m in METRICS},
        years_used=("saidi_wo_med", "count"),
    ).reset_index()
    result["data_through_year"] = last
    result["reliability_need"] = percentile_rank(result["saidi_wo_med_5y"])
    return result
