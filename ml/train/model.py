"""Propensity model v1: LightGBM Poisson on ACS features, exposure = eligible homes, per-city offset.
A small Poisson GLM on a handful of features runs alongside as the "is the tree model worth it" check.

  uv run python -m train.model

offset = log(exposure) + log(city install rate in the training rows), so trees explain the rate *within*
a city and never spend splits on the Austin / San Antonio permitting gap. Scores are the raw log-rate relative
to the city, only meaningful as a ranking inside a metro.

Evaluations, all scored within city with train.baselines.evaluate:
1. spatial CV x time (headline): train on 2021-2023 in 4/5 of the spatial blocks, rank the held-out blocks,
   check where the 2024-2025 installs landed. Past installs are allowed to see the held-out blocks' history,
   so the model has to match a baseline that knows more than it does.
2. spatial CV, 2021-2025: same folds, full label; more installs, less noise.
3. leave one city out: train on one city, rank the other (2021-2025).
4. transfer to Fort Worth (never trained on): fit on Austin + San Antonio, rank Fort Worth block groups, score
   against its battery installs (its only visible label). Fit once on the backup label, once on batteries.
5. Base Power 2026 (Austin): do the spatial out-of-fold scores (2021-2025 label) point to where Base sold?
Outputs: data/processed/model_v1.txt (fit on all rows, 2021-2025), data/processed/train_bg_oof.parquet
"""
from __future__ import annotations

import geopandas as gpd
import lightgbm as lgb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from scipy.optimize import minimize

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
    city_rate = df.groupby("city")[y].sum() / df.groupby("city")["exposure"].sum()
    return (np.log(df["exposure"]) + np.log(df["city"].map(city_rate))).to_numpy()


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


GLM_FEATURES = {  # name -> transform; picked from the SHAP ranking, logs for the skewed ones
    "log_home_value": lambda d: np.log(d["median_home_value"]),
    "log_income": lambda d: np.log(d["median_hh_income"]),
    "log_density": lambda d: np.log1p(d["housing_density_km2"]),
    "pct_sfd": lambda d: d["pct_sfd"],
    "pct_hh_65plus": lambda d: d["pct_hh_65plus"],
    "avg_hh_size_owner": lambda d: d["avg_hh_size_owner"],
    "pct_wfh": lambda d: d["pct_wfh"],
}
GLM_L2 = 1.0


def _glm_x(df: pd.DataFrame, center: pd.Series | None = None, scale: pd.Series | None = None):
    x = pd.DataFrame({k: f(df) for k, f in GLM_FEATURES.items()}, index=df.index)
    center = x.median() if center is None else center
    scale = x.std() if scale is None else scale
    return ((x.fillna(center) - center) / scale).to_numpy(), center, scale


def fit_glm(df: pd.DataFrame, y: str, feats: list[str] | None = None) -> dict:
    """Poisson regression with the same offset as the trees, small ridge penalty."""
    x, center, scale = _glm_x(df)
    x1, off, yy = np.c_[np.ones(len(x)), x], offset(df, y), df[y].to_numpy()

    def loss(b):
        eta = off + x1 @ b
        mu = np.exp(eta)
        pen = GLM_L2 * (b[1:] @ b[1:])
        return (mu - yy * eta).sum() + pen, x1.T @ (mu - yy) + np.r_[0, 2 * GLM_L2 * b[1:]]

    b = minimize(loss, np.zeros(x1.shape[1]), jac=True, method="L-BFGS-B").x
    return {"coef": b, "center": center, "scale": scale}


def score_glm(m: dict, df: pd.DataFrame, feats: list[str] | None = None) -> pd.Series:
    x, _, _ = _glm_x(df, m["center"], m["scale"])
    return pd.Series(np.c_[np.ones(len(x)), x] @ m["coef"], index=df.index)


MODELS = {"LGBM": (fit, score), "GLM": (fit_glm, score_glm)}
TRAIN_CITIES = ["austin", "san_antonio"]
HOLDOUT_CITY = "fort_worth"


def spatial_folds(df: pd.DataFrame) -> pd.Series:
    """Folds of BLOCK_KM x BLOCK_KM grid cells, so neighbours don't sit on both sides of a split."""
    bg = gpd.read_file(f"zip://{TIGER_BG}", columns=["GEOID"]).set_index("GEOID").to_crs(5070)
    c = bg.loc[df["GEOID"]].geometry.centroid
    cell = pd.Series(list(zip((c.x // (BLOCK_KM * 1000)).astype(int), (c.y // (BLOCK_KM * 1000)).astype(int))),
                     index=df.index)
    cells = cell.unique()
    fold_of = dict(zip(cells, np.random.default_rng(0).permutation(len(cells)) % N_FOLDS))
    return cell.map(fold_of)


def oof_scores(df: pd.DataFrame, y: str, feats: list[str], folds: pd.Series, model: str) -> pd.Series:
    fit_fn, score_fn = MODELS[model]
    out = pd.Series(np.nan, index=df.index)
    for k in range(N_FOLDS):
        test = folds == k
        out[test] = score_fn(fit_fn(df[~test], y, feats), df[test], feats)
    return out


def compare(df: pd.DataFrame, model_scores: dict[str, pd.Series], y: str, baselines: list[str]) -> pd.DataFrame:
    rows = []
    for city, d in df.groupby("city"):
        rows += [{"city": city, "score": m, **evaluate(d, s[d.index], y)} for m, s in model_scores.items()]
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
    full = pd.read_parquet(PROCESSED / "train_bg.parquet")
    df = full[full["city"].isin(TRAIN_CITIES)].reset_index(drop=True)
    fw = full[full["city"] == HOLDOUT_CITY].reset_index(drop=True)
    feats = acs_features(pd.DataFrame(columns=pq.read_schema(PROCESSED / "bg_acs_2024.parquet").names))
    folds = spatial_folds(df)
    print(f"{len(df):,} rows, {len(feats)} features, {folds.nunique()} spatial folds "
          f"({BLOCK_KM} km blocks), rows per fold {folds.value_counts().sort_index().tolist()}\n")

    base = ["income only", "home value only"]
    oof_time = {m: oof_scores(df, "y_2021_2023", feats, folds, m) for m in MODELS}
    print("1. spatial CV x time: train 2021-2023, test 2024-2025 on held-out blocks")
    print(compare(df, oof_time, "y_2024_2025", base + ["past installs 2021-23 (rate)"]).to_string(), "\n")

    oof_all = {m: oof_scores(df, "y", feats, folds, m) for m in MODELS}
    print("2. spatial CV, 2021-2025")
    print(compare(df, oof_all, "y", base).to_string(), "\n")

    loco = {m: pd.Series(np.nan, index=df.index) for m in MODELS}
    for city in df["city"].unique():
        test = df["city"] == city
        for m, (fit_fn, score_fn) in MODELS.items():
            loco[m][test] = score_fn(fit_fn(df[~test], "y", feats), df[test], feats)
    print("3. leave one city out (train on the other city), 2021-2025")
    print(compare(df, loco, "y", base).to_string(), "\n")

    if len(fw):
        print(f"4. transfer to Fort Worth ({len(fw)} block groups, {fw['y_battery'].sum()} battery installs "
              f"2021-2025), never trained on")
        fw_scores = {}
        for label in ["y", "y_battery"]:
            for m, (fit_fn, score_fn) in MODELS.items():
                fw_scores[f"{m} on {label}"] = score_fn(fit_fn(df, label, feats), fw, feats)
        print(compare(fw, fw_scores, "y_battery", base).to_string(), "\n")

    austin = df["city"] == "austin"
    if df.loc[austin, "base_power_2026"].sum():
        d = df[austin]
        print(f"5. Base Power 2026 installs in Austin ({d['base_power_2026'].sum()}), spatial out-of-fold scores")
        s5 = {**{m: oof_all[m][d.index] for m in MODELS},
              "past backup installs 2021-25 (rate)": d["y"] / d["exposure"]}
        print(compare(d, s5, "base_power_2026", base).to_string(), "\n")

    glm = fit_glm(df, "y")
    print("GLM coefficients (per 1 sd, log-rate):",
          ", ".join(f"{k} {v:+.2f}" for k, v in zip(GLM_FEATURES, glm["coef"][1:])), "\n")

    final = fit(df, "y", feats)
    print("SHAP, final model (direction: +1 = higher value -> higher propensity)")
    print(explain(final, df, feats).head(15).to_string())

    final[0].save_model(PROCESSED / "model_v1.txt")
    for i, b in enumerate(final[1:], 1):
        b.save_model(PROCESSED / f"model_v1_seed{i}.txt")
    df[["GEOID", "city"]].assign(fold=folds, **{f"{k}_{m.lower()}": v[m] for k, v in
                                                 {"oof_time": oof_time, "oof_all": oof_all, "loco": loco}.items()
                                                 for m in MODELS}) \
        .to_parquet(PROCESSED / "train_bg_oof.parquet", index=False)


if __name__ == "__main__":
    main()
