"""Home propensity score for every owner-occupied single-family parcel, and an H3 resolution-8 cell layer.

  uv run python -m score.homes

Rule (train/homes.py, README "Home-level test"): score = log(appraised value) + log(2) if the home has a solar
permit (value doubled for solar homes). Ranked within each metro as a percentile, since appraisal levels differ by
metro. Homes with a backup install already (generator or battery permit, any year) are flagged and not ranked.
Solar (solar-only permits) and backup are known only where we have permits (Austin, San Antonio city limits); elsewhere it is 0, so those
homes rank on value alone. Homes without an appraisal (Tarrant's StratMap file has no values at all) fall back to
their block group's ACS median home value: value_source = "acs_block_group" instead of "appraisal".

Inputs:  data/interim/parcels_{county}.parquet   (parcels.normalize)
         data/processed/permit_events.parquet     (solar permits)
Outputs: data/processed/home_scores.parquet       one row per eligible home
         data/processed/h3_scores.parquet          one row per H3 res-8 cell with eligible homes
"""
from __future__ import annotations

import geopandas as gpd
import h3
import numpy as np
import pandas as pd

from train.build_table import PROCESSED, ROOT

INTERIM = ROOT / "data" / "interim"
METROS = {
    "austin": ["travis", "williamson", "hays", "bastrop"],
    "san_antonio": ["bexar", "comal", "guadalupe", "kendall"],
    "dfw": ["dallas", "tarrant", "collin", "denton", "rockwall", "kaufman", "ellis", "johnson", "parker"],
    "houston": ["harris", "fort_bend", "montgomery", "brazoria", "galveston"],
}
SOLAR_MULTIPLIER = 2.0
MIN_VALUE = 10_000
H3_RES = 8
TOP_SHARE = 0.2
COLUMNS = ["county", "prop_id", "type_source", "market_value", "year_built", "living_sqft", "lot_sqft"]


def permit_points() -> gpd.GeoDataFrame:
    """Built permits with coordinates: solar-only permits, and backup installs (generator / battery, any installer)."""
    ev = pd.read_parquet(PROCESSED / "permit_events.parquet")
    ev = ev[~ev["not_built"] & ev["lat"].notna() & (ev["solar_install"] | ev["backup_install"] | ev["base_power"])]
    kind = np.where(ev["backup_install"] | ev["base_power"], "backup", "solar")
    return gpd.GeoDataFrame({"kind": kind}, geometry=gpd.points_from_xy(ev["lon"], ev["lat"]), crs=4326)


def load_county(county: str, permits: gpd.GeoDataFrame) -> pd.DataFrame | None:
    path = INTERIM / f"parcels_{county}.parquet"
    if not path.exists():
        print(f"  {county}: no parcels file, skipped")
        return None
    p = gpd.read_parquet(path)
    if "type_source" not in p:  # files normalized before type_source existed (county-service adapters)
        p["type_source"] = "state_code"
    p = p[(p["home_type"] == "sfr_detached") & p["homestead"]]
    p = p.reset_index(drop=True)
    hit = gpd.sjoin(permits.to_crs(p.crs), p[["geometry"]], how="inner", predicate="within")
    pt = p.geometry.representative_point().to_crs(4326)
    out = pd.DataFrame(p[COLUMNS])
    out["has_backup"] = out.index.isin(hit.loc[hit["kind"] == "backup", "index_right"])
    out["has_solar"] = (out.index.isin(hit.loc[hit["kind"] == "solar", "index_right"]) & ~out["has_backup"]).astype(int)
    out["lat"], out["lon"] = pt.y.values, pt.x.values
    return out


def main():
    permits = permit_points()
    frames = []
    for metro, counties in METROS.items():
        for county in counties:
            df = load_county(county, permits)
            if df is not None:
                frames.append(df.assign(metro=metro))
    h = pd.concat(frames, ignore_index=True)
    h["h3_8"] = [h3.latlng_to_cell(la, lo, H3_RES) for la, lo in zip(h["lat"], h["lon"])]
    bg = gpd.read_file(f"zip://{ROOT / 'data/raw/tiger/tl_2020_48_bg.zip'}", columns=["GEOID"]).to_crs(4326)
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(h["lon"], h["lat"]), crs=4326)
    h["GEOID"] = gpd.sjoin(pts, bg, how="left", predicate="within").groupby(level=0)["GEOID"].first()
    acs = pd.read_parquet(PROCESSED / "bg_acs_2024.parquet", columns=["GEOID", "median_home_value"])
    appraised = h["market_value"] >= MIN_VALUE
    h["value"] = h["market_value"].where(appraised, h["GEOID"].map(acs.set_index("GEOID")["median_home_value"]))
    h["value_source"] = np.where(appraised, "appraisal", np.where(h["value"].notna(), "acs_block_group", "none"))
    h = h[h["value"].notna()].reset_index(drop=True)
    h["score"] = np.log(h["value"]) + np.log(SOLAR_MULTIPLIER) * h["has_solar"]
    # Homes that already have backup power are not leads: kept for the map, left out of the ranking.
    h["score"] = h["score"].mask(h["has_backup"])
    h["pct_metro"] = h.groupby("metro")["score"].rank(pct=True)
    h["top20_metro"] = h["pct_metro"] > 1 - TOP_SHARE
    h.to_parquet(PROCESSED / "home_scores.parquet", index=False)

    cells = h.groupby("h3_8").agg(
        metro=("metro", "first"), homes=("prop_id", "size"), median_value=("value", "median"),
        appraised_share=("value_source", lambda s: (s == "appraisal").mean()),
        solar_homes=("has_solar", "sum"), backup_homes=("has_backup", "sum"), mean_pct=("pct_metro", "mean"), top20_homes=("top20_metro", "sum"),
    ).reset_index()
    cells["top20_share"] = cells["top20_homes"] / cells["homes"]
    cells.to_parquet(PROCESSED / "h3_scores.parquet", index=False)

    print(h.groupby(["metro", "county"]).agg(homes=("prop_id", "size"), median_value=("value", "median"),
                                             appraised=("value_source", lambda s: (s == "appraisal").mean()),
                                             solar=("has_solar", "sum"), backup=("has_backup", "sum"),
                                             value_rule=("type_source", lambda s: (s == "value_rule").mean()))
          .round(2).to_string())
    print(f"\n{len(h):,} homes -> home_scores.parquet; {len(cells):,} H3 res-{H3_RES} cells -> h3_scores.parquet "
          f"(median {cells['homes'].median():.0f} homes per cell)")


if __name__ == "__main__":
    main()
