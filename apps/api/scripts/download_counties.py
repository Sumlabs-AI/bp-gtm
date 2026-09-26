"""Write each Market's county boundary to app/geo/counties/ (committed; seeding is offline).

    uv run python -m scripts.download_counties   # from apps/api (imports app.need)

Source: US Census cartographic boundary file (counties, 1:500k), selected by GEOID.
"""

import json

import geopandas as gpd

from app.need.markets import MARKETS

YEAR = 2024
URL = f"https://www2.census.gov/geo/tiger/GENZ{YEAR}/shp/cb_{YEAR}_us_county_500k.zip"


def main() -> None:
    counties = gpd.read_file(URL).set_index("GEOID").to_crs(4326)
    for market in MARKETS:
        row = counties.loc[[market.geoid]]
        feature = json.loads(row[["NAME", "geometry"]].to_json(to_wgs84=True))["features"][0]
        feature["properties"] = {
            "geoid": market.geoid,
            "name": row.iloc[0]["NAMELSAD"],
            "source": URL,
        }
        market.path.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}))
        print(f"{market.name}: {feature['properties']['name']} → {market.path.name}")


if __name__ == "__main__":
    main()
