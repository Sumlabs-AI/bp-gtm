"""Harris Central Appraisal District parcel polygons -> one map point per account.

https://download.hcad.org/data/GIS/Parcels.zip is a zipped Esri file geodatabase
(~210 MB, ~1.5M parcels, Texas South Central state plane EPSG:2278), refreshed a few times
a year. HCAD_NUM_1 is the same 13-digit account as the CAMA exports, so no geocoding is
needed. We keep a point guaranteed to be inside each parcel (representative point), in WGS84.
"""

from pathlib import Path

import httpx
import pandas as pd
import pyogrio

from app.leads.frames import PARCEL_COLUMNS

SOURCE_ID = "hcad_parcels"
URL = "https://download.hcad.org/data/GIS/Parcels.zip"
_UA = {"User-Agent": "base-power-gtm/0.1"}


def fingerprint() -> str:
    resp = httpx.head(URL, headers=_UA, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    h = resp.headers
    return f"{h.get('last-modified', '')}:{h.get('etag', '')}:{h.get('content-length', '')}"


def fetch(raw_dir: Path) -> list[Path]:
    path = raw_dir / "Parcels.zip"
    with httpx.stream("GET", URL, headers=_UA, follow_redirects=True, timeout=600) as resp:
        resp.raise_for_status()
        with path.open("wb") as out:
            for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                out.write(chunk)
    return [path]


def _dataset(zip_path: Path) -> str:
    """GDAL path to the first geodatabase (or GeoJSON, used by tests) inside the ZIP."""
    import zipfile

    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if ".gdb/" in name:
                return f"/vsizip/{zip_path}/{name.split('.gdb/')[0]}.gdb"
            if name.endswith(".geojson"):
                return f"/vsizip/{zip_path}/{name}"
    raise ValueError(f"No parcel dataset in {zip_path}")


def parse(paths: list[Path]) -> pd.DataFrame:
    parcels = pyogrio.read_dataframe(_dataset(paths[0]), columns=["HCAD_NUM_1"])
    parcels = parcels[parcels.geometry.notna() & ~parcels.geometry.is_empty]
    # Stacked/duplicate polygons share an account: keep the largest piece.
    parcels = parcels.assign(area=parcels.geometry.area).sort_values("area", ascending=False)
    parcels = parcels.drop_duplicates("HCAD_NUM_1")
    points = parcels.geometry.representative_point().to_crs(4326)
    return pd.DataFrame(
        {
            "county": "harris",
            "account": parcels["HCAD_NUM_1"].astype(str).str.strip(),
            "lat": points.y.round(6),
            "lon": points.x.round(6),
        }
    )[PARCEL_COLUMNS]
