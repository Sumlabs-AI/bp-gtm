"""Baselines the model has to beat, scored within each city on 2024-2025 installs.

  uv run python -m train.baselines

Ranking only: each baseline orders block groups inside a city, and we ask where the 2024-2025 installs landed.
- capture@k: share of the city's 2024-2025 installs in its top k% of block groups by score.
- spearman: rank correlation of score with the 2024-2025 install rate, block groups with >= 50 eligible homes.
- capture_auc: area under the capture curve (x = share of eligible homes, best score first; y = share of
  installs). The count version of ROC AUC: 0.5 = random, 1 = perfect. Weighting by homes means big block
  groups don't get credit just for being big.
- homes@20: share of installs found by knocking the top 20% of eligible homes.
Scores rank on rate (per eligible home, `exposure`); a model scored the same way is directly comparable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from train.build_table import PROCESSED

TEST = "y_2024_2025"
MIN_HOMES_FOR_RATE = 50

BASELINES = {
    "income only": lambda d: d["median_hh_income"],
    "home value only": lambda d: d["median_home_value"],
    "past installs 2021-23 (rate)": lambda d: d["y_2021_2023"] / d["exposure"],
    "random": lambda d: pd.Series(np.random.default_rng(0).random(len(d)), index=d.index),
}


def capture(score: pd.Series, y: pd.Series, k: float) -> float:
    top = score.rank(ascending=False, method="first") <= np.ceil(k * len(score))
    return y[top].sum() / y.sum()


def capture_curve(score: pd.Series, y: pd.Series, homes: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    o = score.sort_values(ascending=False, kind="stable").index
    return np.r_[0, homes[o].cumsum() / homes.sum()], np.r_[0, y[o].cumsum() / y.sum()]


def evaluate(df: pd.DataFrame, score: pd.Series, y: str = TEST) -> dict[str, float]:
    s = score.fillna(score.median())  # a handful of suppressed ACS medians
    rate = df[y] / df["exposure"]
    big = df["exposure"] >= MIN_HOMES_FOR_RATE
    x, c = capture_curve(s, df[y], df["exposure"])
    return {"capture@10": capture(s, df[y], 0.10), "capture@20": capture(s, df[y], 0.20),
            "homes@20": np.interp(0.2, x, c), "capture_auc": np.trapezoid(c, x),
            "spearman": s[big].rank().corr(rate[big].rank())}


def main():
    df = pd.read_parquet(PROCESSED / "train_bg.parquet")
    rows = []
    for city, d in df.groupby("city"):
        for name, f in BASELINES.items():
            rows.append({"city": city, "baseline": name, **evaluate(d, f(d))})
    out = pd.DataFrame(rows).set_index(["city", "baseline"])
    print(f"2024-2025 installs: {df.groupby('city')[TEST].sum().to_dict()}\n")
    print(out.round(3).to_string())


if __name__ == "__main__":
    main()
