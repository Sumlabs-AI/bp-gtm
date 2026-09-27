"""Training table: one row per block group inside a permit city, label + exposure + features.

  uv run python -m train.build_table

Inputs:  data/processed/bg_permits.parquet     label counts (block group x city x year)
         data/processed/bg_city_share.parquet  share of each block group inside Austin / San Antonio
         data/processed/bg_acs_2024.parquet    ACS 2020-2024 features, eligible_homes exposure
         data/processed/bg_parcels.parquet     parcel features (6 counties), second exposure
Output:  data/processed/train_bg.parquet

Choices (see README "Training table"):
- Cities: Austin and San Antonio train the model (backup label = generator or battery). Fort Worth rows are
  validation only: its generators sit on trade permits without descriptions, so its label is batteries.
  `y_battery` (= aux_battery_install) is the like-for-like label across all three.
- Rows: block groups >= 90% inside the permit city (permits only cover city limits) with eligible_homes > 0.
- Label: backup installs 2021-2025. 2026 is partial; pre-2021 has no San Antonio data. Per-year columns kept
  for the temporal split (train 2021-2023, test 2024-2025) and the without-Uri check (drop 2021).
- Exposure: `exposure` = parcel eligible homes (owner-occupied single-family detached) where the block group has
  parcels, else ACS eligible_homes x the median parcel/ACS ratio. ACS undercounts eligible homes in mixed block
  groups, which inflated their rate and taught the model a spurious negative single-family effect. Exposure only
  sets the rate being learned; scores rank on rate, so scoring outside parcel counties still works.
- Features: ACS only. Parcel columns are carried with a `parcel_` prefix for the installable multiplier and
  sensitivity checks, not for the propensity model: several are filled in only one county (sq ft: Bexar,
  deed year: Travis), so with two training cities they would act as a city indicator.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"

MIN_SHARE_IN_CITY = 0.9
LABEL_YEARS = range(2021, 2026)
LABEL = "backup_install"
# Other permit counts kept for display / segment layers, never as features (same source as the label).
AUX = ["gen_install", "battery_install", "solar_install", "panel_upgrade", "ev_charger", "backup_not_built", "base_power"]

# Least stable between ACS 2017-2021 and 2020-2024 (acs/ANALYSIS.md, rho <= 0.46): mostly sampling noise.
UNSTABLE_ACS = ["median_owner_cost_pct", "pct_owner_cost_burdened", "pct_owner_moved_recent"]
ACS_META = ["acs_vintage", "population", "housing_units", "occupied_units", "eligible_homes", "no_households",
            "acs_low_confidence", "moe_pct_owner_sfd", "cv_median_hh_income", "cv_median_home_value", "land_km2"]


def acs_features(acs: pd.DataFrame) -> list[str]:
    """Model features: ACS values, minus meta/quality columns, censoring/tract-fill flags and unstable ones."""
    skip = set(ACS_META) | set(UNSTABLE_ACS)
    return [c for c in acs.columns
            if c != "GEOID" and c not in skip and not c.endswith(("_censored", "_from_tract"))]


def label_counts(permits: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    p = permits.merge(rows[["GEOID", "city"]], on=["GEOID", "city"])
    p = p[p["year"].isin(LABEL_YEARS)]
    per_year = p.pivot_table(index="GEOID", columns="year", values=LABEL, aggfunc="sum")
    per_year.columns = [f"y_{y}" for y in per_year.columns]
    out = per_year.reindex(columns=[f"y_{y}" for y in LABEL_YEARS])
    out["y"] = out.sum(axis=1)
    out["y_2021_2023"] = out[["y_2021", "y_2022", "y_2023"]].sum(axis=1)
    out["y_2024_2025"] = out[["y_2024", "y_2025"]].sum(axis=1)
    out["y_no_uri"] = out["y"] - out["y_2021"]
    aux = p.groupby("GEOID")[AUX].sum().add_prefix("aux_")
    return out.join(aux, how="outer").reset_index()


def build() -> tuple[pd.DataFrame, list[str]]:
    permits = pd.read_parquet(PROCESSED / "bg_permits.parquet")
    share = pd.read_parquet(PROCESSED / "bg_city_share.parquet")
    acs = pd.read_parquet(PROCESSED / "bg_acs_2024.parquet")
    parcels = pd.read_parquet(PROCESSED / "bg_parcels.parquet")

    rows = share[share["share_in_city"] >= MIN_SHARE_IN_CITY]
    df = rows.merge(acs, on="GEOID", how="left", validate="one_to_one")
    n_in_city = len(df)
    df = df[df["eligible_homes"] > 0]

    df = df.merge(label_counts(permits, df), on="GEOID", how="left", validate="one_to_one")
    ycols = [c for c in df.columns if c.startswith(("y_", "aux_"))] + ["y"]
    df[ycols] = df[ycols].fillna(0).astype(int)

    df["y_battery"] = df["aux_battery_install"]
    # Base Power's own installs (Austin, 2026 only so far): the exact product, outside the label window.
    base = permits[permits["year"] == 2026].merge(df[["GEOID", "city"]], on=["GEOID", "city"])
    df["base_power_2026"] = df["GEOID"].map(base.groupby("GEOID")["base_power"].sum()).fillna(0).astype(int)
    df["label_kind"] = np.where(df["city"] == "fort_worth", "battery_only", "backup")

    df = df.merge(parcels.drop(columns="county").add_prefix("parcel_").rename(columns={"parcel_GEOID": "GEOID"}),
                  on="GEOID", how="left", validate="one_to_one")
    df["has_parcels"] = df["parcel_n_parcels"].notna()
    use_parcels = df["parcel_n_eligible_homes"].fillna(0) > 0
    ratio = (df.loc[use_parcels, "parcel_n_eligible_homes"] / df.loc[use_parcels, "eligible_homes"]).median()
    df["exposure"] = df["parcel_n_eligible_homes"].where(use_parcels, df["eligible_homes"] * ratio)
    df["exposure_source"] = np.where(use_parcels, "parcels", "acs")
    df["rate_per_1k"] = 1000 * df["y"] / df["exposure"]

    check(df, permits, n_in_city, acs)
    return df, acs_features(acs)


def check(df: pd.DataFrame, permits: pd.DataFrame, n_in_city: int, acs: pd.DataFrame) -> None:
    assert df["GEOID"].is_unique, "duplicate GEOID"
    assert df["GEOID"].str.len().eq(12).all()
    assert df["acs_vintage"].notna().all(), "block group missing from ACS"
    # Every label install in a kept block group of its own city made it into the table.
    kept = permits.merge(df[["GEOID", "city"]], on=["GEOID", "city"])
    expected = int(kept.loc[kept["year"].isin(LABEL_YEARS), LABEL].sum())
    assert int(df["y"].sum()) == expected, (int(df["y"].sum()), expected)
    assert (df[[f"y_{y}" for y in LABEL_YEARS]].sum(axis=1) == df["y"]).all()

    print(f"{n_in_city:,} block groups >= {MIN_SHARE_IN_CITY:.0%} in a permit city; "
          f"{n_in_city - len(df)} dropped for zero eligible homes -> {len(df):,} rows")
    total = permits.loc[permits["year"].isin(LABEL_YEARS)].groupby("city")[LABEL].sum()
    summary = df.groupby("city").agg(rows=("GEOID", "size"), installs=("y", "sum"),
                                     eligible_homes=("eligible_homes", "sum"),
                                     zero_label=("y", lambda s: (s == 0).mean()),
                                     has_parcels=("has_parcels", "mean"))
    summary["share_of_city_installs"] = summary["installs"] / total
    summary["rate_per_1k"] = 1000 * summary["installs"] / summary["eligible_homes"]
    print(summary.round(3).to_string())
    print("\ninstalls by year:")
    print(df.groupby("city")[[f"y_{y}" for y in LABEL_YEARS]].sum().to_string())

    feats = acs_features(acs)
    miss = df[feats].isna().mean()
    print(f"\n{len(feats)} ACS features; missing > 0: "
          + (", ".join(f"{c} {v:.1%}" for c, v in miss[miss > 0].sort_values(ascending=False).items()) or "none"))
    print(f"exposure from parcels: {(df['exposure_source'] == 'parcels').mean():.1%}")
    print(f"low-confidence ACS rows: {df['acs_low_confidence'].mean():.1%}; "
          f"eligible_homes < 50: {(df['eligible_homes'] < 50).mean():.1%}")
    both = df[df["has_parcels"]]
    print(f"ACS vs parcel eligible homes (n={len(both)}): corr {both['eligible_homes'].corr(both['parcel_n_eligible_homes']):.2f}, "
          f"median ratio {(both['parcel_n_eligible_homes'] / both['eligible_homes']).median():.2f}")


def main():
    df, feats = build()
    out = PROCESSED / "train_bg.parquet"
    df.to_parquet(out, index=False)
    print(f"\n-> {out.relative_to(ROOT)} ({len(df):,} rows x {df.shape[1]} cols)")
    print("features:", ", ".join(feats))


if __name__ == "__main__":
    main()
