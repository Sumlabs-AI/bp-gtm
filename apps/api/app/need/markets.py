"""Markets: named areas whose Cells we seed. Config only; Cells don't record their Market.

To add a Texas county: add it here, run scripts/download_counties.py, commit the GeoJSON,
then `python -m app.need seed --market <name>`.
"""

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pandas as pd
import shapely
from shapely.geometry import shape

COUNTIES_DIR = Path(__file__).resolve().parents[1] / "geo/counties"


@dataclass(frozen=True)
class Market:
    name: str
    label: str
    geoid: str  # Census county GEOID: state FIPS + county FIPS

    @property
    def path(self) -> Path:
        return COUNTIES_DIR / f"tx-{self.name}.geojson"

    def geometry(self) -> dict:
        """The county (Multi)Polygon from the committed file (no network)."""
        return json.loads(self.path.read_text())["features"][0]["geometry"]


MARKETS = (
    Market("harris", "Harris County (Houston)", "48201"),
    Market("travis", "Travis County (Austin)", "48453"),
)
MARKETS_BY_NAME = {m.name: m for m in MARKETS}


@cache
def _county_shapes() -> list[tuple[str, shapely.Geometry]]:
    shapes = [(m.geoid, shape(m.geometry())) for m in MARKETS]
    for _, geometry in shapes:
        shapely.prepare(geometry)
    return shapes


def county_for_points(lat: pd.Series, lon: pd.Series) -> pd.Series:
    """The Market county (GEOID) each point falls in, or None."""
    result = pd.Series(None, index=lat.index, dtype=object)
    for geoid, geometry in _county_shapes():
        inside = shapely.contains_xy(geometry, lon.to_numpy(), lat.to_numpy())
        result[inside & result.isna().to_numpy()] = geoid
    return result
