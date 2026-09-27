"""Step 1: pull appraisal-district parcels (polygons + home attributes) from county ArcGIS services.

  uv run python -m parcels.fetch                  # training counties (Travis, Bexar)
  uv run python -m parcels.fetch --counties bexar

Output: data/raw/parcels/{county}/*.geojson   one page of <= 1000 parcels per file (resumable cache)
        data/interim/parcels_raw_{county}.parquet   GeoParquet, EPSG:4326, source field names

Owner names are never requested (privacy: block-group aggregates only). Travis' mailing address
is fetched only to derive an owner-occupied flag in normalize; it never reaches interim/processed.

Sources (both return geoJSON, 1000 rows per page, ~0.5 s per page):
  - Travis  Travis County TNR monthly copy of TCAD parcels. Has land state code, year built,
            mailing address (owner-occupancy proxy), deed number (starts with the recording year).
            No living sq ft, no exemption codes (homesite value is set on 96% of homes: not usable).
  - Bexar   Bexar County GIS copy of BCAD parcels. Has state code, gross building area (sq ft),
            year built, stories, exemption codes (HS = homestead). No deed date.
The TxGIO statewide StratMap download (data.geographic.texas.gov) returned 403 from our
network and its web service has query disabled, so each county is wired separately.
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "parcels"
INTERIM = ROOT / "data" / "interim"

PAGE = 1000
SOURCES = {
    "travis": {
        "url": "https://gis.traviscountytx.gov/server1/rest/services/Boundaries_and_Jurisdictions/TCAD/MapServer/0",
        # py_address (mailing address) is only compared with the situs in normalize, then dropped.
        "fields": ["OBJECTID", "PROP_ID", "situs_num", "situs_street", "situs_address", "situs_zip",
                   "py_address", "land_state_cd", "land_type_desc",
                   "F1year_imprv", "market_value", "imprv_homesite_val", "imprv_non_homesite_val",
                   "land_homesite_val", "deed_num", "tcad_acres", "GIS_acres"],
    },
    "bexar": {
        "url": "https://maps.bexar.org/arcgis/rest/services/Parcels/MapServer/0",
        "fields": ["OBJECTID", "PropID", "Situs", "Zip", "State_cd", "PropUse", "GBA", "TOT_GBA", "YrBlt",
                   "Stories", "Houses", "Exempts", "TotVal", "ImprVal", "LandVal", "Acres", "LglAcres"],
    },
}


def _object_ids(url: str) -> list[int]:
    r = requests.get(f"{url}/query", params={"where": "1=1", "returnIdsOnly": "true", "f": "json"}, timeout=300)
    r.raise_for_status()
    return sorted(r.json()["objectIds"])


def _page(url: str, fields: list[str], lo: int, hi: int, out: Path) -> Path:
    if out.exists():
        return out
    params = {
        "where": f"OBJECTID >= {lo} AND OBJECTID <= {hi}",
        "outFields": ",".join(fields),
        "returnGeometry": "true",
        "outSR": 4326,
        "geometryPrecision": 6,
        "f": "geojson",
    }
    for attempt in range(4):
        try:
            r = requests.get(f"{url}/query", params=params, timeout=120)
            r.raise_for_status()
            body = r.json()
            if "error" in body:
                raise RuntimeError(body["error"])
            break
        except (requests.RequestException, RuntimeError, json.JSONDecodeError):
            if attempt == 3:
                raise
    tmp = out.with_suffix(".part")
    tmp.write_text(json.dumps(body))
    tmp.rename(out)
    return out


def fetch(county: str, workers: int = 6) -> Path:
    src = SOURCES[county]
    cache = RAW / county
    cache.mkdir(parents=True, exist_ok=True)
    ids = _object_ids(src["url"])
    # Windows of PAGE consecutive ids (ids can have gaps, so a window may hold fewer rows).
    windows = [(ids[i], ids[min(i + PAGE, len(ids)) - 1]) for i in range(0, len(ids), PAGE)]
    with ThreadPoolExecutor(workers) as pool:
        futs = [pool.submit(_page, src["url"], src["fields"], lo, hi, cache / f"{lo:09d}.geojson") for lo, hi in windows]
        files = [f.result() for f in tqdm(futs, desc=county)]

    frames = [gpd.read_file(f) for f in files]
    gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")
    gdf = gdf.drop_duplicates("OBJECTID")
    assert len(gdf) == len(ids), f"{county}: {len(gdf)} rows vs {len(ids)} ids"
    INTERIM.mkdir(parents=True, exist_ok=True)
    out = INTERIM / f"parcels_raw_{county}.parquet"
    gdf.to_parquet(out)
    print(f"{county}: {len(gdf):,} parcels -> {out}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--counties", nargs="+", default=["travis", "bexar"], choices=list(SOURCES))
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    for c in args.counties:
        fetch(c, args.workers)


if __name__ == "__main__":
    main()
