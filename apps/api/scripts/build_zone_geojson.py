"""Build the ERCOT load zone map layer used by the web app.

    uv run python scripts/build_zone_geojson.py

Sources (both public ArcGIS feature services; boundaries are approximate):
- Houston/North/South/West: "ERCOT Load Zones" layer published on ArcGIS Online (ICF, 2022).
- Austin Energy / CPS Energy: HIFLD Electric Retail Service Territories.
LZ_LCRA and LZ_RAYBN have no contiguous geography, so they are not drawn.
"""

import json
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[2] / "web/public/geo/ercot-zones.geojson"

LOAD_ZONES = (
    "https://services3.arcgis.com/fwwoCWVtaahwlvxO/arcgis/rest/services/"
    "ERCOT_Load_Zones/FeatureServer/7/query"
)
TERRITORIES = (
    "https://services3.arcgis.com/OYP7N6mAJJCyH6hd/arcgis/rest/services/"
    "Electric_Retail_Service_Territories_HIFLD/FeatureServer/0/query"
)
LOAD_ZONE_CODES = {
    "Houston": "LZ_HOUSTON",
    "North": "LZ_NORTH",
    "South": "LZ_SOUTH",
    "West": "LZ_WEST",
}
TERRITORY_CODES = {"AUSTIN ENERGY": "LZ_AEN", "CITY OF SAN ANTONIO - (TX)": "LZ_CPS"}

# ~1 km simplification and ~100 m precision keep the file small; zones are coarse anyway.
SIMPLIFY = {"outSR": 4326, "maxAllowableOffset": 0.01, "geometryPrecision": 3, "f": "geojson"}


def query(url: str, where: str, name_field: str, codes: dict[str, str]) -> list[dict]:
    params = {"where": where, "outFields": name_field, **SIMPLIFY}
    features = httpx.get(url, params=params, timeout=120).raise_for_status().json()["features"]
    return [
        {
            "type": "Feature",
            "properties": {"code": codes[f["properties"][name_field]]},
            "geometry": f["geometry"],
        }
        for f in features
    ]


def main() -> None:
    names = ", ".join(f"'{n}'" for n in TERRITORY_CODES)
    features = query(LOAD_ZONES, "1=1", "NAME", LOAD_ZONE_CODES) + query(
        TERRITORIES, f"NAME IN ({names})", "NAME", TERRITORY_CODES
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    print(f"Wrote {len(features)} zones to {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
