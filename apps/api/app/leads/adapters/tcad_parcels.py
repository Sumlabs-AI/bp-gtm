"""Travis parcel polygons (same TCAD layer as app/leads/adapters/tcad.py) -> one map point per
account: a point guaranteed to be inside the parcel, in WGS84."""

import json
from pathlib import Path

import pandas as pd
from shapely.geometry import shape

from app.leads.adapters.tcad import fetch_pages
from app.leads.adapters.tcad import fingerprint as tcad_fingerprint
from app.leads.frames import PARCEL_COLUMNS

SOURCE_ID = "tcad_parcels"


def fingerprint() -> str:
    return tcad_fingerprint()


def fetch(raw_dir: Path) -> list[Path]:
    return fetch_pages(raw_dir, ["PROP_ID"], geometry=True)


def _point(geometry: dict | None) -> tuple[float, float] | None:
    if not geometry or not geometry.get("rings"):
        return None
    polygon = shape({"type": "Polygon", "coordinates": geometry["rings"]})
    if polygon.is_empty:
        return None
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    p = polygon.representative_point()
    return p.y, p.x


def parse(paths: list[Path]) -> pd.DataFrame:
    rows = []
    for path in paths:
        for f in json.loads(path.read_text()):
            prop_id = f["attributes"].get("PROP_ID")
            point = _point(f.get("geometry"))
            if prop_id is not None and point is not None:
                rows.append(("travis", str(int(prop_id)), *point))
    return pd.DataFrame(rows, columns=PARCEL_COLUMNS)
