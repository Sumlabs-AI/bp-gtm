"""Step 3: parcels -> 2020 block groups: home features, eligible-home exposure, installable share.

  uv run python -m parcels.aggregate

Input:  data/interim/parcels_{county}.parquet   (parcels.normalize)
        data/raw/tiger/tl_2020_48_{bg,place}.zip
Output: data/processed/bg_parcels.parquet        one row per block group with any parcel

Each parcel lands in the block group containing its representative point (always inside the
polygon, unlike a centroid on an L-shaped lot). Medians over fewer than MIN_N homes are NaN.

Installable rules come from Base's help center (clearances, 20 ft to meter, 100-200A panels,
Austin 150-200A, nothing above 200A). Parcel data can't see the panel or the meter, so each
rule is a proxy; all thresholds live in INSTALL_RULES so an answer from Base is a one-line change.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
INTERIM, PROCESSED, TIGER = ROOT / "data" / "interim", ROOT / "data" / "processed", ROOT / "data" / "raw" / "tiger"

MIN_N = 10
RECENT_SALE_SINCE = 2025  # deed recorded this year or later = "new owner" segment
RESIDENTIAL = ["sfr_detached", "sfr_attached", "mobile", "condo", "multifamily"]
INSTALL_RULES = {
    # > 200A service can't host Base; very large homes usually have 320-400A service. Guess, not a Base number.
    "max_living_sqft": 4_500,
    # Austin Energy requires a 150-200A panel; homes built before 1980 often have 100A or older panels.
    "austin_min_year_built": 1980,
}


def _load() -> gpd.GeoDataFrame:
    files = sorted(INTERIM.glob("parcels_*.parquet"))
    files = [f for f in files if not f.name.startswith("parcels_raw_")]
    return gpd.GeoDataFrame(pd.concat([gpd.read_parquet(f) for f in files], ignore_index=True), crs="EPSG:4326")


def assign_block_groups(p: gpd.GeoDataFrame) -> pd.DataFrame:
    bg = gpd.read_file(f"zip://{TIGER / 'tl_2020_48_bg.zip'}")[["GEOID", "geometry"]]
    austin = gpd.read_file(f"zip://{TIGER / 'tl_2020_48_place.zip'}").query("NAME == 'Austin'")[["geometry"]]
    pts = gpd.GeoDataFrame(p.drop(columns="geometry"), geometry=p.geometry.representative_point(), crs=p.crs)
    pts = pts.to_crs(bg.crs)
    pts = gpd.sjoin(pts, bg, how="left", predicate="within").drop(columns="index_right")
    # Austin Energy territory ~ City of Austin limits (approximation; the utility also serves a few
    # areas outside the city and not all of the city).
    in_austin = gpd.sjoin(pts[["geometry"]], austin.to_crs(bg.crs), how="left", predicate="within")
    pts["austin_energy"] = in_austin["index_right"].notna().groupby(level=0).any()
    return pd.DataFrame(pts.drop(columns="geometry"))


def installable(p: pd.DataFrame) -> pd.Series:
    r = INSTALL_RULES
    ok = p["home_type"].eq("sfr_detached")
    ok &= ~(p["living_sqft"] > r["max_living_sqft"])  # unknown sq ft passes
    old = p["year_built"] < r["austin_min_year_built"]
    ok &= ~(p["austin_energy"] & old)
    return ok


def aggregate(p: pd.DataFrame) -> pd.DataFrame:
    p = p[p["GEOID"].notna()].copy()
    p["res"] = p["home_type"].isin(RESIDENTIAL)
    p["sfr"] = p["home_type"].str.startswith("sfr")
    p["sfr_det"] = p["home_type"].eq("sfr_detached")
    p["eligible"] = p["sfr_det"] & p["homestead"]
    p["installable"] = installable(p)
    flag = lambda cond, col: cond.astype(float).where(p[col].notna())  # NaN when the input is unknown
    p["pre1980"] = flag(p["year_built"] < 1980, "year_built")
    p["large_home"] = flag(p["living_sqft"] > INSTALL_RULES["max_living_sqft"], "living_sqft")
    p["recent_sale"] = flag(p["deed_year"] >= RECENT_SALE_SINCE, "deed_year")

    g = p.groupby("GEOID")
    out = pd.DataFrame({
        "county": g["county"].agg(lambda s: s.mode().iat[0]),
        "n_parcels": g.size(),
        "n_res_parcels": g["res"].sum(),
        "n_sfr": g["sfr"].sum(),
        "n_sfr_detached": g["sfr_det"].sum(),
        "n_eligible_homes": g["eligible"].sum(),  # exposure for the Poisson label
        "n_installable": g["installable"].sum(),
    })
    res = out["n_res_parcels"].replace(0, np.nan)
    out["share_sfr_detached"] = out["n_sfr_detached"] / res
    out["share_sfr_attached"] = (out["n_sfr"] - out["n_sfr_detached"]) / res
    out["share_mobile"] = p[p["res"]].groupby("GEOID")["home_type"].apply(lambda s: s.eq("mobile").mean())
    out["installable_share"] = out["n_installable"] / res

    sfr = p[p["sfr"]].groupby("GEOID")
    out["share_homestead"] = sfr["homestead"].mean()
    for col in ["pre1980", "large_home", "recent_sale"]:
        out[f"share_{col}"] = sfr[col].mean()

    det = p[p["sfr_det"]].groupby("GEOID")
    for col, name in [("living_sqft", "med_living_sqft"), ("lot_sqft", "med_lot_sqft"),
                      ("year_built", "med_year_built_parcel"), ("market_value", "med_market_value")]:
        med, n = det[col].median(), det[col].count()
        out[name] = med.where(n >= MIN_N)
    for col in ["share_homestead", "share_pre1980", "share_large_home", "share_recent_sale"]:
        out[col] = out[col].where(out["n_sfr"] >= MIN_N)
    return out.reset_index()


def main() -> None:
    p = assign_block_groups(_load())
    print(f"{len(p):,} parcels; {p['GEOID'].isna().mean():.2%} outside any block group")
    out = aggregate(p)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    path = PROCESSED / "bg_parcels.parquet"
    out.to_parquet(path, index=False)
    print(f"{len(out):,} block groups -> {path}")
    print(out.groupby("county")[["n_eligible_homes", "installable_share", "share_homestead",
                                 "med_living_sqft", "med_year_built_parcel"]].median().round(2).to_string())


if __name__ == "__main__":
    main()
