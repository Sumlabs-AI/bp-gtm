"""Baseline Weather Need pipeline: download (cached) -> features -> Postgres.

Raw files land in data/raw/ (gitignored): IEM warning polygons per year, nClimGrid county
Parquet per month, and the Texas outline for the res-6 Reference Population grid.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import geopandas as gpd
import httpx
import pandas as pd

from app import geo
from app.db import SessionLocal
from app.need.config import weather as config
from app.need.weather.store import save_county_temperature, save_storm_features
from app.need.weather.storms import RESOLUTION, storm_features, warning_cells
from app.need.weather.temperature import county_temperature_features

DATA = Path(__file__).resolve().parents[3] / "data"
RAW_IEM, RAW_NCLIM, RAW_CENSUS = DATA / "raw/iem", DATA / "raw/nclimgrid", DATA / "raw/census"
TEXAS = RAW_CENSUS / "texas.geojson"
TEXAS_COUNTIES = RAW_CENSUS / "tx-counties.geojson"

IEM_URL = (
    "https://mesonet.agron.iastate.edu/cgi-bin/request/gis/watchwarn.py"
    "?accept=shapefile&states=TX&limit1=yes&sts={year}-01-01T00:00Z&ets={next}-01-01T00:00Z"
)
NCLIM_URL = (
    "https://noaa-nclimgrid-daily-pds.s3.amazonaws.com/EpiNOAA/v1-0-0/parquet/cty/"
    "YEAR={year}/STATUS={status}/{year}{month:02d}.parquet"
)
COUNTIES_URL = "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_500k.zip"


def _years() -> range:
    this_year = date.today().year
    return range(this_year - config.window_years, this_year + 1)


def _get(client: httpx.Client, url: str, path: Path) -> bool:
    """Download to `path`; False (nothing written) when the file doesn't exist upstream."""
    response = client.get(url)
    if response.status_code == 404:
        return False
    response.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return True


def download() -> None:
    RAW_IEM.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=600, follow_redirects=True) as client:
        for year in _years():
            path = RAW_IEM / f"sbw{year}.zip"
            # Past years are final; the current year grows, so it's always refreshed.
            if path.exists() and year < date.today().year:
                print(f"IEM warnings {year}: cached")
                continue
            try:
                found = _get(client, IEM_URL.format(year=year, next=year + 1), path)
            except httpx.HTTPError as exc:
                found = False
                print(f"IEM warnings {year}: FAILED ({exc}); keeping the previous file")
            else:
                print(f"IEM warnings {year}: {'downloaded' if found else 'not available'}")

        for year in _years():
            for month in range(1, 13):
                if date(year, month, 1) > date.today():
                    break
                stem = f"{year}{month:02d}"
                if (RAW_NCLIM / f"{stem}-scaled.parquet").exists():
                    continue
                # Prefer the final "scaled" release; recent months only exist as "prelim".
                for status in ("scaled", "prelim"):
                    path = RAW_NCLIM / f"{stem}-{status}.parquet"
                    url = NCLIM_URL.format(year=year, month=month, status=status)
                    if _get(client, url, path):
                        if status == "scaled":
                            (RAW_NCLIM / f"{stem}-prelim.parquet").unlink(missing_ok=True)
                        print(f"nClimGrid {stem}: {status}")
                        break
                else:
                    print(f"nClimGrid {stem}: not published yet")

    if not TEXAS.exists() or not TEXAS_COUNTIES.exists():
        counties = gpd.read_file(COUNTIES_URL)
        counties = counties[counties["STATEFP"] == "48"].to_crs(4326)[["GEOID", "geometry"]]
        RAW_CENSUS.mkdir(parents=True, exist_ok=True)
        counties.to_file(TEXAS_COUNTIES, driver="GeoJSON")
        counties.dissolve()[["geometry"]].to_file(TEXAS, driver="GeoJSON")
        print("Texas outline and counties: downloaded")


def county_of_cells(cells: list[str]) -> dict[str, str | None]:
    """H3 cells -> Census county GEOID containing their center (statewide; None offshore)."""
    if not TEXAS_COUNTIES.exists():
        raise SystemExit("No Texas counties file: run `python -m app.need weather download`.")
    counties = gpd.read_file(TEXAS_COUNTIES)
    centers = [geo.cell_to_center(h) for h in cells]
    points = gpd.GeoDataFrame(
        {"h3": cells},
        geometry=gpd.points_from_xy([c[1] for c in centers], [c[0] for c in centers]),
        crs=4326,
    )
    hits = gpd.sjoin(points, counties, predicate="within").drop_duplicates("h3")
    found = dict(zip(hits["h3"], hits["GEOID"], strict=True))
    return {h: found.get(h) for h in cells}


def load_warnings() -> pd.DataFrame:
    frames = []
    for path in sorted(RAW_IEM.glob("sbw*.zip")):
        g = gpd.read_file(
            path, columns=["WFO", "PHENOM", "SIG", "GTYPE", "ETN", "ISSUED", "EXPIRED"]
        )
        frames.append(g.to_crs(4326))
    w = pd.concat(frames, ignore_index=True)
    return pd.DataFrame(
        {
            "wfo": w["WFO"],
            "phenom": w["PHENOM"],
            "sig": w["SIG"],
            "gtype": w["GTYPE"],
            "etn": w["ETN"],
            "issued": pd.to_datetime(w["ISSUED"], format="%Y%m%d%H%M", utc=True),
            "expired": pd.to_datetime(w["EXPIRED"], format="%Y%m%d%H%M", utc=True),
            "geometry": w.geometry,
        }
    )


def texas_grid() -> list[str]:
    texas = gpd.read_file(TEXAS).geometry.iloc[0]
    return sorted(geo.polygon_to_cells(texas.__geo_interface__, RESOLUTION))


def storm_data_through() -> date:
    """Last full day the warning archive covers: the day before the current-year file was
    fetched (or Dec 31 of the latest year downloaded). Not the last warning's date: days
    without warnings are still covered, and a quiet week mustn't look like missing data."""
    latest = max(RAW_IEM.glob("sbw*.zip"))
    year = int(latest.stem[3:])
    fetched = datetime.fromtimestamp(latest.stat().st_mtime, UTC).date() - timedelta(days=1)
    return min(fetched, date(year, 12, 31))


@dataclass
class ComputeReport:
    warnings: int
    grid_cells: int
    storm_data_through: date
    counties: int
    temperature_data_through: date


def _require_files() -> None:
    if not any(RAW_IEM.glob("sbw*.zip")) or not any(RAW_NCLIM.glob("*.parquet")):
        raise SystemExit("No weather files: run `python -m app.need weather download`.")


def build_storms() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Storm hits and res-6 Storm features (no database)."""
    _require_files()
    hits = warning_cells(load_warnings())
    return hits, storm_features(hits, texas_grid(), storm_data_through(), config.window_years)


def build_temperature() -> pd.DataFrame:
    """County Temperature Extremes features (no database)."""
    _require_files()
    return county_temperature_features(sorted(RAW_NCLIM.glob("*.parquet")), config)


def compute() -> ComputeReport:
    hits, storms = build_storms()
    temps = build_temperature()
    with SessionLocal() as db:
        now = datetime.now(UTC)
        save_storm_features(db, storms, now)
        save_county_temperature(db, temps, now)
        db.commit()
    report = ComputeReport(
        warnings=int(hits["warning"].nunique()),
        grid_cells=len(storms),
        storm_data_through=storms["data_through"].iloc[0],
        counties=len(temps),
        temperature_data_through=temps["data_through"].iloc[0],
    )
    return report
