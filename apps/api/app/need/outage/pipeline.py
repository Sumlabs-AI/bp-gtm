"""Baseline Outage Need pipeline: download (cached) -> Texas Parquet -> features -> Postgres.

Raw files land in data/raw/ (gitignored, never in Postgres); the normalized Parquet in
data/derived/. Both are reused when unchanged.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pandas as pd

from app.db import SessionLocal
from app.need.config import outage_events as rules
from app.need.config import outage_exposure as exposure
from app.need.outage import eaglei, eia
from app.need.outage.events import SAMPLE_HOURS, detect_events
from app.need.outage.store import save_county_features, save_utility_reliability

DATA = Path(__file__).resolve().parents[3] / "data"
RAW_EAGLEI, RAW_EIA = DATA / "raw/eaglei", DATA / "raw/eia861"
PARQUET = DATA / "derived/eaglei_tx.parquet"


def _fetch(client: httpx.Client, url: str, path: Path, size: int | None = None) -> bool:
    """Download unless the file is already there (with the expected size, when known)."""
    if path.exists() and (size is None or path.stat().st_size == size):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    with client.stream("GET", url, follow_redirects=True) as response:
        response.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in response.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.rename(path)
    return True


def download() -> None:
    with httpx.Client(timeout=600) as client:
        files = client.get(eaglei.FIGSHARE_ARTICLE).raise_for_status().json()["files"]
        yearly = sorted(
            (f for f in files if f["name"].startswith("eaglei_outages_")), key=lambda f: f["name"]
        )[-exposure.window_years :]
        for f in [*yearly, *(f for f in files if f["name"] == "MCC.csv")]:
            new = _fetch(client, f["download_url"], RAW_EAGLEI / f["name"], f["size"])
            print(f"EAGLE-I {f['name']}: {'downloaded' if new else 'cached'}")

        # Final releases only: early-release files are named f861<year>er.zip and never match.
        found = 0
        for year in range(date.today().year - 1, date.today().year - 10, -1):
            path = RAW_EIA / f"f861{year}.zip"
            for url in (eia.ZIP_URL.format(year=year), eia.ARCHIVE_URL.format(year=year)):
                try:
                    new = _fetch(client, url, path)
                    if not _is_zip(path):
                        path.unlink()
                        continue
                    print(f"EIA-861 {year}: {'downloaded' if new else 'cached'}")
                    found += 1
                    break
                except httpx.HTTPError:  # missing year, or a transient network failure
                    continue
            if found == exposure.window_years:
                break


def _is_zip(path: Path) -> bool:
    with path.open("rb") as f:
        return f.read(2) == b"PK"


@dataclass
class ComputeReport:
    parquet_rows: int
    data_through: date
    counties: int
    counties_in_reference: int
    utilities: int
    utilities_ranked: int


def compute() -> ComputeReport:
    csvs = sorted(RAW_EAGLEI.glob("eaglei_outages_*.csv"))[-exposure.window_years :]
    zips = sorted(RAW_EIA.glob("f861*.zip"))[-exposure.window_years :]
    if not csvs or not zips:
        raise SystemExit("No EAGLE-I/EIA-861 files: run `python -m app.need outage download`.")
    if not PARQUET.exists() or PARQUET.stat().st_mtime < max(p.stat().st_mtime for p in csvs):
        PARQUET.parent.mkdir(parents=True, exist_ok=True)
        print(f"Normalizing {len(csvs)} EAGLE-I files to Texas Parquet…", flush=True)
        eaglei.normalize(csvs, PARQUET)
    customers = eaglei.modeled_customers(RAW_EAGLEI / "MCC.csv")
    counties = eaglei.county_features(PARQUET, customers, rules, exposure)

    utilities = eia.utility_reliability(
        pd.concat([eia.parse_reliability(z) for z in zips]), exposure.window_years
    )

    now = datetime.now(UTC)
    with SessionLocal() as db:
        save_county_features(db, counties, now)
        save_utility_reliability(db, utilities, now)
        db.commit()
    return ComputeReport(
        parquet_rows=eaglei.row_count(PARQUET),
        data_through=counties["data_through"].iloc[0],
        counties=len(counties),
        counties_in_reference=int(counties["in_reference"].sum()),
        utilities=len(utilities),
        utilities_ranked=int(utilities["reliability_need"].notna().sum()),
    )


def major_events(fips: str) -> pd.DataFrame:
    """The county's Major Outage Events in the window (for validation / debugging)."""
    customers = eaglei.modeled_customers(RAW_EAGLEI / "MCC.csv")[fips]
    series = eaglei.county_series(PARQUET, fips)
    events = detect_events(series, customers, rules)
    events = events[events["major"]].copy()
    events["peak_pct_out"] = events["peak_customers_out"] / customers
    events["hours_per_customer"] = events["customer_hours"] / customers
    return events


def yearly_hours_per_customer(fips: str) -> pd.Series:
    """EAGLE-I outage hours per customer by calendar year (compare with EIA SAIDI)."""
    customers = eaglei.modeled_customers(RAW_EAGLEI / "MCC.csv")[fips]
    series = eaglei.county_series(PARQUET, fips)
    series = series[series["customers_out"] <= customers]
    return series.groupby(series["ts"].dt.year)["customers_out"].sum() * SAMPLE_HOURS / customers


def yearly_events(fips: str) -> pd.DataFrame:
    """Outage Events and Major Outage Events per calendar year."""
    customers = eaglei.modeled_customers(RAW_EAGLEI / "MCC.csv")[fips]
    events = detect_events(eaglei.county_series(PARQUET, fips), customers, rules)
    by_year = events.groupby(events["start"].dt.year)
    return pd.DataFrame({"events": by_year.size(), "major": by_year["major"].sum()})


def utility_saidi(utility_id: int) -> pd.Series:
    """EIA SAIDI with major events, minutes per customer by year (for the cross-check)."""
    zips = sorted(RAW_EIA.glob("f861*.zip"))[-exposure.window_years :]
    yearly = pd.concat([eia.parse_reliability(z) for z in zips])
    return yearly[yearly["utility_id"] == utility_id].set_index("year")["saidi_w_med"]
