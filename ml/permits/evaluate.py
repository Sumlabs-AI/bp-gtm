"""Score keyword baseline vs Jev against the hand-labeled gold set.

  uv run python -m permits.evaluate            # both halves, per field + final label
  uv run python -m permits.evaluate --split tune
  uv run python -m permits.evaluate --labels llm   # against raw LLM pre-labels

Tune wording and thresholds on "tune" only; quote "test" numbers.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from permits.gold import GOLD, LABELS, SAMPLE, final_labels
from permits.label import EQUIPMENT, backup_install, jev_fields, keyword_fields


def load(labels=LABELS) -> pd.DataFrame:
    g = pd.read_csv(SAMPLE, dtype=str)
    lab = final_labels() if labels == "final" else pd.read_csv(labels, dtype=str).fillna("")
    jev = pd.read_parquet(GOLD / "gold_jev.parquet")
    jev = jev[["gold_id"] + [c for c in jev.columns if c.startswith("p_") or c.endswith("_conf")]
              + ["action", "property"]].rename(columns={"action": "action_jev", "property": "property_jev"})
    df = g.merge(lab, on="gold_id").merge(jev, on="gold_id")
    for k in EQUIPMENT:
        df[k] = df[k] == "1"
    return df


def gold_fields(df: pd.DataFrame) -> pd.DataFrame:
    return df[EQUIPMENT + ["action", "property"]]


def compare(df: pd.DataFrame, yes: float) -> pd.DataFrame:
    gold = gold_fields(df)
    kw = keyword_fields(df)
    jv = jev_fields(df.drop(columns=["action", "property"])
                    .rename(columns={"action_jev": "action", "property_jev": "property"}), yes)
    rows = []
    for f in EQUIPMENT + ["action", "property"]:
        rows.append({"field": f, "keyword": (kw[f] == gold[f]).mean(), "jev": (jv[f] == gold[f]).mean(),
                     "n": len(df), "gold_yes": gold[f].mean() if f in EQUIPMENT else np.nan})
    y = backup_install(gold)
    for name, pred in [("keyword", backup_install(kw)), ("jev", backup_install(jv))]:
        tp, fp, fn = (pred & y).sum(), (pred & ~y).sum(), (~pred & y).sum()
        rows.append({"field": f"backup_install [{name}]", name: (pred == y).mean(),
                     "precision": tp / max(tp + fp, 1), "recall": tp / max(tp + fn, 1), "n": len(df), "gold_yes": y.mean()})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["tune", "test", "all"], default="all")
    ap.add_argument("--yes", type=float, default=0.5, help="Noul threshold")
    ap.add_argument("--labels", choices=["final", "hand", "llm"], default="final",
                    help="final = LLM labels overridden by hand review")
    args = ap.parse_args()
    df = load({"final": "final", "hand": LABELS, "llm": GOLD / "labels_llm_gpt-6-astra.csv"}[args.labels])
    if "source" in df:
        print(df.source.value_counts().to_string())
    print(f"{len(df)} labeled permits")
    splits = ["tune", "test"] if args.split == "all" else [args.split]
    with pd.option_context("display.width", 200, "display.float_format", "{:.3f}".format):
        for s in splits:
            part = df[df.split == s]
            if part.empty:
                continue
            print(f"\n== {s} (n={len(part)})")
            print(compare(part, args.yes).to_string(index=False))


if __name__ == "__main__":
    main()
