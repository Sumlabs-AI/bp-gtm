"""Home-level test: does per-home parcel data rank buyers better than the block group's home value?

  uv run python -m train.homes

Universe: owner-occupied single-family detached parcels (homestead flag) in the training block groups
(>= 90% inside the city): Travis parcels for Austin, Bexar parcels for San Antonio.
Label: the parcel got a built backup install (generator or battery, Base Power excluded), located by the
permit's coordinates falling inside the parcel polygon.

Evaluation per city, same 5 km spatial folds as train.model: train on 2021-2023 installs in 4/5 of the blocks,
rank the held-out homes that had no 2021-2023 install, check who installed in 2024-2025.
- roc_auc: per home, installed 2024-2025 or not (0.5 random).
- top10 / top20: share of 2024-2025 installers among the top 10% / 20% of homes by score.
Scores: the block group's median home value (ACS, the current rule), the home's own appraised value, and
LightGBM on home features alone, then home + block-group ACS features. Features differ by county
(sq ft / stories only in Bexar, deed year only in Travis), so each city gets its own model.
Output: data/processed/train_home.parquet
"""
from __future__ import annotations

import geopandas as gpd
import h3
import lightgbm as lgb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from train.build_table import PROCESSED, ROOT, acs_features
from train.model import spatial_folds

INTERIM = ROOT / "data" / "interim"
CITY_COUNTY = {"austin": "travis", "san_antonio": "bexar"}
HOME_FEATURES = {
    "austin": ["log_value", "rel_value", "year_built", "log_lot", "deed_year"],
    "san_antonio": ["log_value", "rel_value", "year_built", "log_lot", "living_sqft", "stories"],
}
# Permit history on the home, known before the 2024-2025 test window. A permit that is itself a backup install
# (e.g. solar + battery) is the label, not a signal.
SIGNALS = {"has_solar": "solar_install", "has_ev": "ev_charger", "has_panel": "panel_upgrade"}
SIGNAL_UNTIL = 2023
PARAMS = {"objective": "binary", "learning_rate": 0.05, "num_leaves": 15, "min_data_in_leaf": 200,
          "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 5.0,
          "num_threads": 8, "verbose": -1, "seed": 0}


def homes(bg: pd.DataFrame) -> pd.DataFrame:
    """Eligible homes in the training block groups, with the install label joined on."""
    allev = pd.read_parquet(PROCESSED / "permit_events.parquet")
    allev = allev[~allev["not_built"] & allev["lat"].notna()]
    ev = allev[allev["backup_install"] & ~allev["base_power"] & allev["year"].between(2021, 2025)]
    sig = allev[~allev["backup_install"] & (allev["year"] <= SIGNAL_UNTIL)]
    out = []
    for city, county in CITY_COUNTY.items():
        p = gpd.read_parquet(INTERIM / f"parcels_{county}.parquet")
        p = p[(p["home_type"] == "sfr_detached") & p["homestead"]].reset_index(drop=True)
        pts = gpd.GeoDataFrame(geometry=p.geometry.representative_point(), crs=p.crs)
        bgs = gpd.read_file(f"zip://{ROOT / 'data/raw/tiger/tl_2020_48_bg.zip'}", columns=["GEOID"]).to_crs(p.crs)
        p["GEOID"] = gpd.sjoin(pts, bgs, how="left", predicate="within").groupby(level=0)["GEOID"].first()
        p = p[p["GEOID"].isin(bg.loc[bg["city"] == city, "GEOID"])].reset_index(drop=True)

        e = ev[(ev["city"] == city) & ev["GEOID"].isin(p["GEOID"].unique())]
        e = gpd.GeoDataFrame(e[["year"]], geometry=gpd.points_from_xy(e["lon"], e["lat"]), crs=4326).to_crs(p.crs)
        hit = gpd.sjoin(e, p[["geometry"]], how="inner", predicate="within")
        first = hit.groupby("index_right")["year"].min()
        allp = gpd.read_parquet(INTERIM / f"parcels_{county}.parquet", columns=["home_type", "homestead", "geometry"])
        any_hit = gpd.sjoin(e, allp, how="left", predicate="within").groupby(level=0).first()
        kind = np.where(any_hit["index_right"].isna(), "no parcel (street / geocode)",
                        np.where(any_hit["home_type"] != "sfr_detached", "other home type",
                                 np.where(any_hit["homestead"], "eligible home", "single-family, no homestead")))
        print(f"{city}: {len(p):,} eligible homes; {len(e):,} installs 2021-2025 in these block groups land on: "
              + ", ".join(f"{k} {v:.0%}" for k, v in pd.Series(kind).value_counts(normalize=True).items()))
        p["install_year"] = first.reindex(p.index)
        s = sig[sig["city"] == city]
        s = gpd.GeoDataFrame(s[list(SIGNALS.values())], geometry=gpd.points_from_xy(s["lon"], s["lat"]),
                             crs=4326).to_crs(p.crs)
        s = gpd.sjoin(s, p[["geometry"]], how="inner", predicate="within")
        for col, cat in SIGNALS.items():
            p[col] = p.index.isin(s.loc[s[cat], "index_right"]).astype(int)
        pt = gpd.GeoSeries(p.geometry.representative_point(), crs=p.crs).to_crs(4326)
        p["lat"], p["lon"] = pt.y.values, pt.x.values
        p["h3_8"] = [h3.latlng_to_cell(la, lo, 8) for la, lo in zip(p["lat"], p["lon"])]
        p["city"] = city
        out.append(pd.DataFrame(p.drop(columns="geometry")))
    h = pd.concat(out, ignore_index=True)
    h["log_value"] = np.log(h["market_value"].clip(lower=10_000))
    h["rel_value"] = h["market_value"] / h.groupby("GEOID")["market_value"].transform("median")
    h["log_lot"] = np.log(h["lot_sqft"].clip(lower=500))
    h["y_2021_2023"] = h["install_year"].between(2021, 2023).astype(int)
    h["y_2024_2025"] = h["install_year"].between(2024, 2025).astype(int)
    return h


def within_auc(score: pd.Series, y: pd.Series, area: pd.Series) -> float:
    """ROC AUC inside each area (block group / H3 cell), averaged with weight = installs in the area.
    Areas with no installs, or only installers, can't rank and are skipped."""
    num = den = 0.0
    for _, idx in y.groupby(area).groups.items():
        yy = y[idx]
        if 0 < yy.sum() < len(yy):
            num += yy.sum() * roc_auc(score[idx], yy)
            den += yy.sum()
    return num / den


def top_share(score: pd.Series, y: pd.Series, k: float) -> float:
    top = score.rank(ascending=False, method="first") <= np.ceil(k * len(score))
    return y[top].sum() / y.sum()


def roc_auc(score: pd.Series, y: pd.Series) -> float:
    r = score.rank()
    n1 = y.sum()
    n0 = len(y) - n1
    return (r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def oof_lgbm(h: pd.DataFrame, feats: list[str], folds: pd.Series) -> pd.Series:
    out = pd.Series(np.nan, index=h.index)
    for k in sorted(folds.unique()):
        tr, te = h[folds != k], h[folds == k]
        ds = lgb.Dataset(tr[feats], tr["y_2021_2023"])
        cv = lgb.cv(PARAMS, ds, num_boost_round=1000, nfold=4, stratified=False,
                    callbacks=[lgb.early_stopping(50, verbose=False)])
        b = lgb.train(PARAMS, ds, num_boost_round=len(cv["valid binary_logloss-mean"]))
        out[te.index] = b.predict(te[feats])
    return out


def main():
    bg = pd.read_parquet(PROCESSED / "train_bg.parquet")
    bg = bg[bg["city"].isin(CITY_COUNTY)].reset_index(drop=True)
    acs = acs_features(pd.DataFrame(columns=pq.read_schema(PROCESSED / "bg_acs_2024.parquet").names))
    h = homes(bg).merge(bg[["GEOID"] + acs], on="GEOID", how="left")
    h.to_parquet(PROCESSED / "train_home.parquet", index=False)

    fold_of = pd.Series(spatial_folds(bg).values, index=bg["GEOID"])
    rows = []
    for city, d in h.groupby("city"):
        d = d.reset_index(drop=True)
        folds = d["GEOID"].map(fold_of)
        home = HOME_FEATURES[city]
        scores = {
            "area home value (ACS block group median)": d["median_home_value"],
            "home's own appraised value": d["market_value"],
            "LightGBM: home features": oof_lgbm(d, home, folds),
            "LightGBM: home + area (ACS) features": oof_lgbm(d, home + acs, folds),
            "LightGBM: home + solar / EV / panel permits": oof_lgbm(d, home + list(SIGNALS), folds),
        }
        test = d["y_2021_2023"] == 0
        y = d.loc[test, "y_2024_2025"]
        print(f"\n{city}: {test.sum():,} test homes, {y.sum()} installed 2024-2025 ({y.mean():.2%})")
        for name, s in scores.items():
            s = s[test].fillna(s.median())
            rows.append({"city": city, "score": name, "roc_auc": roc_auc(s, y),
                         "top10": top_share(s, y, 0.10), "top20": top_share(s, y, 0.20),
                         "auc_within_bg": within_auc(s, y, d.loc[test, "GEOID"]),
                         "auc_within_h3_8": within_auc(s, y, d.loc[test, "h3_8"])})
        t = d[test]
        dec = pd.qcut(t["market_value"].rank(method="first"), 5, labels=[f"value q{i}" for i in range(1, 6)])
        print("2024-2025 installs per 1,000 homes, by value quintile and permit history (homes in brackets):")
        for col in SIGNALS:
            g = t.groupby([dec, t[col]], observed=True)["y_2024_2025"].agg(["mean", "size"])
            tab = (1000 * g["mean"]).round(1).astype(str) + " (" + g["size"].astype(str) + ")"
            print(f"  {col}:", tab.unstack().rename(columns={0: "no", 1: "yes"}).to_dict("index"))
    print()
    print(pd.DataFrame(rows).set_index(["city", "score"]).round(3).to_string())


if __name__ == "__main__":
    main()
