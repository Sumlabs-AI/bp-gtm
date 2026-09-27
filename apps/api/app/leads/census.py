"""Census data used by the consumption estimate: the share of occupied housing units heated
with electricity (ACS 5-year table B25040) per block group, with block-group shapes (TIGER).

Both come from census.gov bulk files, which need no API key. They're downloaded once into
data/raw/census/ (delete that folder to refresh when a new ACS vintage is out).
"""

from pathlib import Path

import geopandas as gpd
import httpx
import pandas as pd

from app.leads.pipeline import RAW_DIR

ACS_URL = (
    "https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/"
    "5YRData/acsdt5y2024-b25040.dat"
)
TIGER_URL = "https://www2.census.gov/geo/tiger/TIGER2024/BG/tl_{state}_bg.zip"
CACHE_DIR = RAW_DIR / "census"
COUNTY_FIPS = {"harris": "48201"}


def _download(url: str) -> Path:
    path = CACHE_DIR / url.rsplit("/", 1)[1]
    if not path.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".part")
        with httpx.stream("GET", url, follow_redirects=True, timeout=600) as response:
            response.raise_for_status()
            with partial.open("wb") as out:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    out.write(chunk)
        partial.rename(path)
    return path


def block_group_heating(county: str = "harris") -> gpd.GeoDataFrame:
    """One row per block group: geoid, households, electric_share, geometry (EPSG:4326)."""
    fips = COUNTY_FIPS[county]
    acs = pd.read_csv(
        _download(ACS_URL),
        sep="|",
        usecols=["GEO_ID", "B25040_E001", "B25040_E004"],  # total, electricity
        dtype={"GEO_ID": str},
    )
    acs = acs[acs["GEO_ID"].str.startswith(f"1500000US{fips}")]
    acs = pd.DataFrame(
        {
            "geoid": acs["GEO_ID"].str.removeprefix("1500000US"),
            "households": acs["B25040_E001"],
            "electric_share": (acs["B25040_E004"] / acs["B25040_E001"]).where(
                acs["B25040_E001"] > 0
            ),
        }
    )
    shapes = gpd.read_file(_download(TIGER_URL.format(state=f"2024_{fips[:2]}")))
    shapes = shapes.loc[shapes["COUNTYFP"] == fips[2:], ["GEOID", "geometry"]]
    shapes = shapes.rename(columns={"GEOID": "geoid"}).to_crs(4326)
    return shapes.merge(acs, on="geoid", how="inner")
