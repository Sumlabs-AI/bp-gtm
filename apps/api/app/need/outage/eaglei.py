"""ORNL EAGLE-I (CC BY 4.0): 15-minute customers-out per county, 2014 onward.

Raw yearly CSVs (1.1-1.4 GB, all US) are normalized once into a Texas-only Parquet
(`fips, county, ts, customers_out`), then county features are computed from it with DuckDB.
Timestamps are UTC, stored naive. Only features reach Postgres.
"""

from datetime import timedelta
from pathlib import Path

import duckdb
import pandas as pd
from pydantic import BaseModel

from app.need.outage.events import SAMPLE_HOURS, EventRules, detect_events
from app.need.percentile import percentile_rank

FIGSHARE_ARTICLE = "https://api.figshare.com/v2/articles/24237376"
TEXAS_FIPS_PREFIX = "48"


class ExposureConfig(BaseModel):
    window_years: int = 5
    # A county joins the Reference Population when EAGLE-I has rows for it in at least this
    # share of the window's calendar years (ORNL publishes coverage per state, not county).
    min_years_share: float = 0.8


def normalize(csv_paths: list[Path], out: Path) -> int:
    """Texas rows of the yearly CSVs -> one Parquet. Columns are read by position because
    headers differ by year (2023 calls customers_out "sum"; 2024 adds total_customers)."""
    selects = [
        f"""SELECT lpad(CAST(column0 AS VARCHAR), 5, '0') AS fips, column1 AS county,
                   CAST(column4 AS TIMESTAMP) AS ts,
                   CAST(column3 AS INTEGER) AS customers_out
            FROM read_csv('{path}', header = true, all_varchar = true,
                          names = ['column0', 'column1', 'column2', 'column3', 'column4'],
                          null_padding = true)
            WHERE starts_with(lpad(CAST(column0 AS VARCHAR), 5, '0'), '{TEXAS_FIPS_PREFIX}')"""
        for path in csv_paths
    ]
    query = " UNION ALL ".join(selects) + " ORDER BY fips, ts"
    with _connect() as con:  # paths are ours (data/raw, data/derived), not user input
        con.execute(f"COPY ({query}) TO '{out}' (FORMAT parquet, COMPRESSION zstd)")
    return row_count(out)


def _connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")  # timestamptz <-> timestamp casts stay in UTC
    return con


def modeled_customers(mcc_csv: Path) -> dict[str, int]:
    """ORNL's modeled customers per Texas county (the denominator for every share)."""
    df = pd.read_csv(mcc_csv, dtype={"County_FIPS": str}, encoding="utf-8-sig")
    df["County_FIPS"] = df["County_FIPS"].str.zfill(5)
    df = df[df["County_FIPS"].str.startswith(TEXAS_FIPS_PREFIX)]
    return dict(zip(df["County_FIPS"], df["Customers"].astype(int), strict=True))


def row_count(parquet: Path) -> int:
    with _connect() as con:
        return con.execute("SELECT count(*) FROM read_parquet(?)", [str(parquet)]).fetchone()[0]


def county_series(
    parquet: Path, fips: str, window: tuple[pd.Timestamp, pd.Timestamp] | None = None
) -> pd.DataFrame:
    """One county's `ts` (UTC), `customers_out` rows, optionally within [start, end)."""
    sql = "SELECT ts::TIMESTAMP AS ts, customers_out FROM read_parquet(?) WHERE fips = ?"
    params: list[object] = [str(parquet), fips]
    if window is not None:
        sql += " AND ts::TIMESTAMP >= ? AND ts::TIMESTAMP < ?"
        params += [pd.Timestamp(t).tz_convert("UTC").tz_localize(None) for t in window]
    with _connect() as con:
        series = con.execute(sql, params).df()
    series["ts"] = pd.to_datetime(series["ts"]).dt.tz_localize("UTC")
    return series


def _window_metrics(
    series: pd.DataFrame, events: pd.DataFrame, customers: int, since: pd.Timestamp
) -> dict[str, float | int]:
    valid = series[(series["ts"] >= since) & (series["customers_out"] <= customers)]
    in_window = events[events["start"] >= since]
    return {
        "hours_per_customer": float(valid["customers_out"].sum()) * SAMPLE_HOURS / customers,
        "outage_events": len(in_window),
        "major_outage_events": int(in_window["major"].sum()),
        "peak_pct_out": float(in_window["peak_customers_out"].max() / customers)
        if len(in_window)
        else 0.0,
    }


def county_features(
    parquet: Path,
    customers: dict[str, int],
    rules: EventRules,
    config: ExposureConfig | None = None,
) -> pd.DataFrame:
    """One row per county in `customers`: raw 365-day and 5-year metrics as of Data Through,
    the Texas percentile of 5-year outage hours per customer = Observed Outage Exposure (null
    outside the Reference Population)."""
    config = config or ExposureConfig()
    with _connect() as con:
        last_ts = con.execute("SELECT max(ts)::TIMESTAMP FROM read_parquet(?)", [str(parquet)])
        data_through = last_ts.fetchone()[0].date()
        names = dict(
            con.execute(
                "SELECT DISTINCT fips, county FROM read_parquet(?)", [str(parquet)]
            ).fetchall()
        )
    window_end = pd.Timestamp(data_through + timedelta(days=1), tz="UTC")
    since_5y = window_end - pd.DateOffset(years=config.window_years)
    since_365d = window_end - pd.Timedelta(days=365)

    rows = []
    for fips, n in sorted(customers.items()):
        series = county_series(parquet, fips, (since_5y, window_end))
        years = int(series["ts"].dt.year.nunique())
        row = {
            "county_fips": fips,
            "county_name": names.get(fips),
            "modeled_customers": n,
            "data_through": data_through,
            "years_observed": years,
            "last_observed_major_outage_on": None,
        }
        if years:
            events = detect_events(series, n, rules)
            for suffix, since in (("365d", since_365d), ("5y", since_5y)):
                for key, value in _window_metrics(series, events, n, since).items():
                    row[f"{key}_{suffix}"] = value
            majors = events[events["major"]]
            if len(majors):
                row["last_observed_major_outage_on"] = majors["start"].max().date()
        rows.append(row)

    features = pd.DataFrame(rows)
    for key in ("hours_per_customer", "outage_events", "major_outage_events", "peak_pct_out"):
        for suffix in ("365d", "5y"):
            if f"{key}_{suffix}" not in features:
                features[f"{key}_{suffix}"] = float("nan")
    features["in_reference"] = (
        features["years_observed"] >= config.min_years_share * config.window_years
    )
    features["hours_per_customer_pctl"] = percentile_rank(
        features["hours_per_customer_5y"], features["in_reference"]
    )
    # Only outage hours per customer is scored: it's size-normalized (a county-level SAIDI)
    # and cross-checks with EIA. Major-event counts favour small counties (one feeder fault
    # crosses 5% of 1,000 customers), so they stay explanatory context, never scored.
    features["observed_exposure"] = features["hours_per_customer_pctl"]
    return features
