"""Propensity model v1: LightGBM Poisson on ACS features, exposure = eligible homes, per-city offset.

  uv run python -m train.model

offset = log(eligible_homes) + log(city install rate in the training rows), so trees explain the rate *within*
a city and never spend splits on the Austin / San Antonio permitting gap. Scores are the raw log-rate relative
to the city, only meaningful as a ranking inside a metro.

Evaluations, all scored within city with train.baselines.evaluate:
1. spatial CV x time (headline): train on 2021-2023 in 4/5 of the spatial blocks, rank the held-out blocks,
   check where the 2024-2025 installs landed. Past installs are allowed to see the held-out blocks' history,
   so the model has to match a baseline that knows more than it does.
2. spatial CV, 2021-2025: same folds, full label; more installs, less noise.
3. leave one city out: train on one city, rank the other (2021-2025).
Outputs: data/processed/model_v1.txt (fit on all rows, 2021-2025), data/processed/train_bg_oof.parquet
"""
from __future__ import annotations

import geopandas as gpd
import lightgbm as lgb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from train.baselines import BASELINES, evaluate
from train.build_table import PROCESSED, ROOT, acs_features

TIGER_BG = ROOT / "data" / "raw" / "tiger" / "tl_2020_48_bg.zip"
BLOCK_KM = 5
N_FOLDS = 5
SEEDS = range(5)
PARAMS = {
    "objective": "poisson", "metric": "poisson", "learning_rate": 0.03, "num_leaves": 7, "max_depth": 3,
    "min_data_in_leaf": 30, "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1,
    "lambda_l2": 5.0, "num_threads": 1, "verbose": -1,  # 1 thread: tiny data, OpenMP overhead dominates
}


def offset(df: pd.DataFrame, y: str) -> np.ndarray:
    city_rate = df.groupby("city")[y].sum() / df.groupby("city")["eligible_homes"].sum()
    return (np.log(df["eligible_homes"]) + np.log(df["city"].map(city_rate))).to_numpy()


def fit(df: pd.DataFrame, y: str, feats: list[str]) -> list[lgb.Booster]:
    """One booster per seed; rounds picked by 5-fold CV on the training rows."""
    boosters = []
    for seed in SEEDS:
        params = {**PARAMS, "seed": seed}
        ds = lgb.Dataset(df[feats], df[y], init_score=offset(df, y), free_raw_data=False)
        cv = lgb.cv(params, ds, num_boost_round=2000, nfold=5, stratified=False, seed=seed,
                    callbacks=[lgb.early_stopping(50, verbose=False)])
        rounds = len(cv["valid poisson-mean"])
        boosters.append(lgb.train(params, ds, num_boost_round=rounds))
    return boosters


def score(boosters: list[lgb.Booster], df: pd.DataFrame, feats: list[str]) -> pd.Series:
    """Log-rate relative to the city base rate (no offset), averaged over seeds."""
    raw = np.mean([b.predict(df[feats], raw_score=True) for b in boosters], axis=0)
    return pd.Series(raw, index=df.index)


def spatial_folds(df: pd.DataFrame) -> pd.Series:
    """Folds of BLOCK_KM x BLOCK_KM grid cells, so neighbours don't sit on both sides of a split."""
    bg = gpd.read_file(f"zip://{TIGER_BG}", columns=["GEOID"]).set_index("GEOID").to_crs(5070)
    c = bg.loc[df["GEOID"]].geometry.centroid
    cell = pd.Series(list(zip((c.x // (BLOCK_KM * 1000)).astype(int), (c.y // (BLOCK_KM * 1000)).astype(int))),
                     index=df.index)
    cells = cell.unique()
    fold_of = dict(zip(cells, np.random.default_rng(0).permutation(len(cells)) % N_FOLDS))
    return cell.map(fold_of)


def oof_scores(df: pd.DataFrame, y: str, feats: list[str], folds: pd.Series) -> pd.Series:
    out = pd.Series(np.nan, index=df.index)
    for k in range(N_FOLDS):
        test = folds == k
        out[test] = score(fit(df[~test], y, feats), df[test], feats)
    return out


def compare(df: pd.DataFrame, model_score: pd.Series, y: str, baselines: list[str]) -> pd.DataFrame:
    rows = []
    for city, d in df.groupby("city"):
        rows.append({"city": city, "score": "MODEL", **evaluate(d, model_score[d.index], y)})
        rows += [{"city": city, "score": b, **evaluate(d, BASELINES[b](d), y)} for b in baselines]
    return pd.DataFrame(rows).set_index(["city", "score"]).round(3)


def explain(boosters: list[lgb.Booster], df: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
    """Mean |SHAP| and the direction (rank corr of feature value with its SHAP value)."""
    shap = np.mean([b.predict(df[feats], pred_contrib=True)[:, :-1] for b in boosters], axis=0)
    shap = pd.DataFrame(shap, columns=feats, index=df.index)
    return pd.DataFrame({
        "mean_abs_shap": shap.abs().mean(),
        "direction": [df[f].rank().corr(shap[f].rank()) for f in feats],
    }).sort_values("mean_abs_shap", ascending=False).round(3)


def main():
    df = pd.read_parquet(PROCESSED / "train_bg.parquet")
    feats = acs_features(pd.DataFrame(columns=pq.read_schema(PROCESSED / "bg_acs_2024.parquet").names))
    folds = spatial_folds(df)
    print(f"{len(df):,} rows, {len(feats)} features, {folds.nunique()} spatial folds "
          f"({BLOCK_KM} km blocks), rows per fold {folds.value_counts().sort_index().tolist()}\n")

    base = ["income only", "home value only"]
    oof_time = oof_scores(df, "y_2021_2023", feats, folds)
    print("1. spatial CV x time: train 2021-2023, test 2024-2025 on held-out blocks")
    print(compare(df, oof_time, "y_2024_2025", base + ["past installs 2021-23 (rate)"]).to_string(), "\n")

    oof_all = oof_scores(df, "y", feats, folds)
    print("2. spatial CV, 2021-2025")
    print(compare(df, oof_all, "y", base).to_string(), "\n")

    loco = pd.Series(np.nan, index=df.index)
    for city in df["city"].unique():
        test = df["city"] == city
        loco[test] = score(fit(df[~test], "y", feats), df[test], feats)
    print("3. leave one city out (train on the other city), 2021-2025")
    print(compare(df, loco, "y", base).to_string(), "\n")

    final = fit(df, "y", feats)
    print("SHAP, final model (direction: +1 = higher value -> higher propensity)")
    print(explain(final, df, feats).head(15).to_string())

    final[0].save_model(PROCESSED / "model_v1.txt")
    for i, b in enumerate(final[1:], 1):
        b.save_model(PROCESSED / f"model_v1_seed{i}.txt")
    df[["GEOID", "city"]].assign(fold=folds, oof_time=oof_time, oof_all=oof_all, loco=loco) \
        .to_parquet(PROCESSED / "train_bg_oof.parquet", index=False)


if __name__ == "__main__":
    main()
