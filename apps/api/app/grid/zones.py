"""ERCOT settlement points we track, with plain-language descriptions."""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import geopandas as gpd
import pandas as pd

ZONES_GEOJSON = Path(__file__).with_name("ercot-zones.geojson")

# Every zone is compared against this system-wide reference price.
REFERENCE_HUB = "HB_HUBAVG"


@dataclass(frozen=True)
class Zone:
    code: str
    name: str
    description: str
    # False for zones without a contiguous geography (shown in lists, not on the map).
    on_map: bool = True


ZONES = [
    Zone("LZ_HOUSTON", "Houston", "Greater Houston and the Gulf Coast (CenterPoint area)."),
    Zone("LZ_NORTH", "North", "Dallas–Fort Worth and North/Central Texas (mostly Oncor)."),
    Zone("LZ_SOUTH", "South", "South Texas, Corpus Christi and the Rio Grande Valley."),
    Zone("LZ_WEST", "West", "West Texas and the Permian Basin; heavy wind and solar."),
    Zone("LZ_AEN", "Austin Energy", "City of Austin municipal utility territory."),
    Zone("LZ_CPS", "CPS Energy", "City of San Antonio municipal utility territory."),
    Zone(
        "LZ_LCRA",
        "LCRA",
        "Lower Colorado River Authority wholesale customers; scattered across Central Texas.",
        on_map=False,
    ),
    Zone(
        "LZ_RAYBN",
        "Rayburn",
        "Rayburn Country Electric Cooperative members in Northeast Texas.",
        on_map=False,
    ),
]

ZONES_BY_CODE = {z.code: z for z in ZONES}
TRACKED_POINTS = [z.code for z in ZONES] + [REFERENCE_HUB]


@cache
def _zone_shapes() -> gpd.GeoDataFrame:
    zones = gpd.read_file(ZONES_GEOJSON)[["code", "geometry"]]
    zones["area"] = zones.to_crs(3081).area  # Texas equal-area projection
    return zones


def zone_for_points(lat: pd.Series, lon: pd.Series) -> pd.Series:
    """The load zone each point falls in (None outside every polygon or without coordinates).

    The one rule for Leads and Cells alike: point inside the zone polygon, and where
    polygons overlap (Austin Energy and CPS sit inside LZ_SOUTH) the smallest one wins.
    Boundaries are approximate (scripts/build_zone_geojson.py); LZ_LCRA and LZ_RAYBN are
    never assigned because they have no polygon.
    """
    zones = _zone_shapes()
    points = gpd.GeoDataFrame(index=lat.index, geometry=gpd.points_from_xy(lon, lat), crs=4326)
    hits = gpd.sjoin(points[points.geometry.is_valid], zones, predicate="within")
    by_point = hits.sort_values("area").groupby(level=0)["code"].first()
    return by_point.reindex(lat.index).astype(object).where(lambda z: z.notna(), None)
