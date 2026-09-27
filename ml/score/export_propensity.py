"""Propensity per H3 res-8 cell in the Need Engine's import format (wiki/ml-contract.md).

  uv run python -m score.export_propensity
  cd ../apps/api && uv run python -m app.need import-propensity ../../ml/output/propensity.parquet

Only the Need Engine's Markets (Harris, Travis) are exported. The file is committed (ml/output/, ~70 KB) so a fresh
clone can import it without rebuilding ml/data.

propensity_score = mean within-metro percentile of the cell's eligible homes (score.homes) x 100: homes are still
ranked against their whole metro (Austin: Travis, Williamson, Hays, Bastrop). It ranks cells inside a metro, not
across metros. Extra columns (county, homes, top20_homes) are ignored by the importer.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from train.build_table import PROCESSED, ROOT

MODEL_VERSION = "home-value-solar-v1"
FEATURE_VERSION = "1.0.0"  # Need Feature Version (apps/api/app/need/config.py); this model uses none of them
COUNTIES = ["harris", "travis"]  # the Need Engine's Markets (apps/api/app/need/markets.py)
OUT = ROOT / "output" / "propensity.parquet"


def main():
    h = pd.read_parquet(PROCESSED / "home_scores.parquet", columns=["county", "h3_8", "pct_metro", "top20_metro"])
    h = h[h["county"].isin(COUNTIES)]
    cells = h.groupby("h3_8").agg(
        county=("county", lambda s: s.mode().iat[0]), homes=("pct_metro", "size"),
        mean_pct=("pct_metro", "mean"), top20_homes=("top20_metro", "sum"),
    ).reset_index()
    cells = cells[cells["mean_pct"].notna()]  # cells whose only homes already have backup
    out = pd.DataFrame({
        "h3_index": cells["h3_8"],
        "propensity_score": (cells["mean_pct"] * 100).clip(0, 100).round(2),
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "scored_at": pd.Timestamp(datetime.now(UTC)),
        "county": cells["county"],
        "homes": cells["homes"],
        "top20_homes": cells["top20_homes"],
    })
    OUT.parent.mkdir(exist_ok=True)
    out.to_parquet(OUT, index=False, compression="zstd")
    print(f"{len(out):,} cells -> {OUT} ({OUT.stat().st_size / 1e6:.2f} MB)")
    print(out.groupby("county")["propensity_score"].describe().round(1).to_string())


if __name__ == "__main__":
    main()
