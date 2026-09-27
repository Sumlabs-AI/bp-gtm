"""ACS step 2: raw ACS columns -> block-group Fit features, with MOE and missing-value handling.

  uv run python -m acs.features [--vintage 2024]

Inputs:  data/interim/acs_<vintage>_{bg,tract}.parquet (acs.fetch)
         data/raw/tiger/tl_2020_48_bg.zip (land area for density)
         data/processed/bg_permits.parquet, bg_city_share.parquet (checks only)
Outputs: data/processed/bg_acs_<vintage>.parquet  one row per 2020 Texas block group (GEOID, 12 chars)
         acs/FEATURES.md  data dictionary, regenerated from FEATURES below (reference vintage only)

Rules:
  - Shares: numerator / table total; NaN (not 0) when the total is 0.
  - Medians: kept as published. `<f>_censored` when the median sits in an open-ended bin
    (e.g. home value 2,000,001 = "$2M+"). Missing block-group medians are filled from the tract
    and flagged `<f>_from_tract`, only where the block group has households.
  - MOE: proportion MOE per Census formula; `acs_low_confidence` marks block groups whose core
    features are too noisy to show without a warning (see LOW_CONF_*).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from acs.fetch import shell_labels
from acs.variables import MOE_CONTROLLED, MOE_OPEN_ENDED

ROOT = Path(__file__).resolve().parents[1]
INTERIM, PROCESSED = ROOT / "data" / "interim", ROOT / "data" / "processed"
TIGER_BG = ROOT / "data" / "raw" / "tiger" / "tl_2020_48_bg.zip"
DOC = Path(__file__).with_name("FEATURES.md")

MIN_HOUSEHOLDS = 50        # fewer occupied units than this -> low confidence
# Block-group ACS is noisy everywhere; these flag the worst ~16% (0.20 / 0.40 would flag ~32%).
LOW_CONF_SHARE_MOE = 0.25  # 90% MOE of pct_owner_sfd above 25 points -> low confidence
LOW_CONF_MEDIAN_CV = 0.50  # CV of median income or home value above this -> low confidence

# FEATURES line ranges were written against this vintage's table shells. Other vintages must use the
# same labels for every line we read, except the ones below (checked in check_line_labels).
REFERENCE_VINTAGE = 2024
VINTAGE_VARYING = {
    "B19013_001",  # income in <vintage> dollars: compare incomes across vintages by rank, not level
    "B25038_003", "B25038_004",  # moved-in brackets follow the survey years
}


@dataclass(frozen=True)
class Feature:
    name: str
    kind: str                # "share" | "median" | "count"
    num: tuple[str, ...]     # ACS columns summed (without _E/_M), e.g. ("B25003_002",)
    den: tuple[str, ...] = ()
    direction: int = 0       # expected effect on backup propensity: +1 / -1 / 0 unknown (monotone hints)
    desc: str = ""
    tract_only: bool = False  # table not published for block groups: tract value copied down


def _r(table: str, a: int, b: int) -> tuple[str, ...]:
    return tuple(f"{table}_{i:03d}" for i in range(a, b + 1))


FEATURES = [
    # exposure / size
    Feature("population", "count", ("B01003_001",), desc="Total population"),
    Feature("housing_units", "count", ("B25001_001",), desc="Housing units"),
    Feature("occupied_units", "count", ("B25003_001",), desc="Occupied housing units (households)"),
    Feature("eligible_homes", "count", ("B25032_003",),
            desc="Owner-occupied single-family detached homes; label exposure (installs per 1,000)"),
    # housing stock and tenure
    Feature("pct_owner", "share", ("B25003_002",), ("B25003_001",), +1, "Owner-occupied share of households"),
    Feature("pct_sfd", "share", ("B25024_002",), ("B25024_001",), +1, "Single-family detached share of housing units"),
    Feature("pct_owner_sfd", "share", ("B25032_003",), ("B25032_001",), +1,
            "Owner-occupied single-family detached share of households"),
    Feature("pct_mobile_home", "share", ("B25024_010",), ("B25024_001",), 0, "Mobile home share of housing units"),
    Feature("pct_built_pre1980", "share", _r("B25034", 7, 11), ("B25034_001",), 0,
            "Built before 1980 (older panels, often 100A)"),
    Feature("pct_built_2010plus", "share", _r("B25034", 2, 3), ("B25034_001",), 0, "Built 2010 or later"),
    Feature("pct_4plus_bedrooms", "share", _r("B25041", 6, 7), ("B25041_001",), 0, "4+ bedrooms (home size)"),
    Feature("pct_vacant", "share", ("B25002_003",), ("B25002_001",), -1, "Vacant share of housing units"),
    Feature("pct_seasonal", "share", ("B25004_006",), ("B25001_001",), 0,
            "Seasonal / recreational share of housing units"),
    # households
    Feature("pct_hh_65plus", "share", ("B11007_002",), ("B11007_001",), 0, "Households with someone 65+"),
    Feature("pct_hh_children", "share", ("B11005_002",), ("B11005_001",), 0, "Households with children under 18"),
    Feature("pct_owner_moved_pre2010", "share", _r("B25038", 6, 8), ("B25038_002",), 0,
            "Owners in the home since before 2010 (long tenure)"),
    Feature("pct_owner_moved_recent", "share", _r("B25038", 3, 4), ("B25038_002",), 0,
            "Owners who moved in recently: the two newest brackets (2024: 2020+, 2022-23: 2018+, 2021: 2015+)"),
    Feature("pct_wfh", "share", ("B08301_021",), ("B08301_001",), 0, "Workers who work from home"),
    # energy
    Feature("pct_heat_electric", "share", ("B25040_004",), ("B25040_001",), 0, "Households heating with electricity"),
    Feature("pct_heat_gas", "share", ("B25040_002",), ("B25040_001",), 0, "Households heating with utility gas"),
    Feature("pct_owner_heat_electric", "share", ("B25117_005",), ("B25117_002",), 0,
            "Owner households heating with electricity", tract_only=True),
    # finances
    Feature("pct_owner_mortgage", "share", ("B25081_002",), ("B25081_001",), 0, "Owners with a mortgage"),
    Feature("pct_owner_cost_burdened", "share", _r("B25091", 8, 11) + _r("B25091", 19, 22),
            ("B25091_001",), 0, "Owners paying 30%+ of income on housing (not-computed rows kept in the base)"),
    # medians
    Feature("median_hh_income", "median", ("B19013_001",), direction=0, desc="Median household income ($)"),
    Feature("median_home_value", "median", ("B25077_001",), direction=0, desc="Median owner home value ($)"),
    Feature("median_year_built", "median", ("B25035_001",), desc="Median year structure built"),
    Feature("median_year_moved_owner", "median", ("B25039_002",), desc="Median year owner householder moved in"),
    Feature("median_rooms", "median", ("B25018_001",), desc="Median rooms per housing unit"),
    Feature("avg_hh_size_owner", "median", ("B25010_002",), desc="Average owner household size (a mean, not a median)"),
    Feature("median_owner_cost_pct", "median", ("B25092_001",), desc="Median owner costs as % of income"),
]


# ---------------------------------------------------------------- helpers
def _est(df: pd.DataFrame, cols: tuple[str, ...]) -> pd.Series:
    t = [c.replace("_", "_E", 1) for c in cols]
    return df[t].sum(axis=1, min_count=len(t))


def _moe(df: pd.DataFrame, cols: tuple[str, ...]) -> pd.Series:
    """MOE of a sum of estimates: sqrt(sum MOE_i^2). Controlled estimates have MOE 0."""
    m = df[[c.replace("_", "_M", 1) for c in cols]]
    m = m.mask(m == MOE_CONTROLLED, 0).mask(m < 0)
    return np.sqrt((m ** 2).sum(axis=1, min_count=m.shape[1]))


def _share(df: pd.DataFrame, f: Feature) -> tuple[pd.Series, pd.Series]:
    x, y = _est(df, f.num), _est(df, f.den)
    mx, my = _moe(df, f.num), _moe(df, f.den)
    p = (x / y).where(y > 0)
    rad = mx ** 2 - p ** 2 * my ** 2
    rad = rad.where(rad >= 0, mx ** 2 + p ** 2 * my ** 2)  # Census: fall back to the ratio formula
    return p, np.sqrt(rad) / y.where(y > 0)


def compute(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (features, moe) frames indexed like df."""
    out, moe = pd.DataFrame(index=df.index), pd.DataFrame(index=df.index)
    for f in FEATURES:
        if f.kind == "share":
            out[f.name], moe[f.name] = _share(df, f)
        else:
            out[f.name], moe[f.name] = _est(df, f.num), _moe(df, f.num)
            if f.kind == "median":
                out[f"{f.name}_censored"] = df[f.num[0].replace("_", "_M", 1)] == MOE_OPEN_ENDED
    return out, moe


# ---------------------------------------------------------------- build
def check_line_labels(vintage: int) -> None:
    """Fail if a line FEATURES reads means something else in this vintage (ACS brackets move)."""
    used = sorted({c for f in FEATURES for c in f.num + f.den} - VINTAGE_VARYING)
    ref, cur = shell_labels(REFERENCE_VINTAGE).reindex(used), shell_labels(vintage).reindex(used)
    diff = ref[ref != cur]
    if len(diff):
        raise SystemExit("ACS line labels differ from the reference vintage; fix FEATURES:\n"
                         + "\n".join(f"  {c}: {ref[c]!r} -> {cur[c]!r}" for c in diff.index))


def build(vintage: int) -> pd.DataFrame:
    check_line_labels(vintage)
    bg_raw = pd.read_parquet(INTERIM / f"acs_{vintage}_bg.parquet").set_index("GEOID")
    tr_raw = pd.read_parquet(INTERIM / f"acs_{vintage}_tract.parquet").set_index("GEOID")
    bg, moe = compute(bg_raw)
    tract, _ = compute(tr_raw)

    has_hh = bg["occupied_units"] > 0
    tract_of = bg.index.str[:11]
    for f in (f for f in FEATURES if f.tract_only):
        bg[f.name] = tract[f.name].reindex(tract_of).to_numpy()
        moe[f.name] = np.nan
    for f in (f for f in FEATURES if f.kind == "median"):
        fill = bg[f.name].isna() & has_hh
        bg[f"{f.name}_from_tract"] = fill
        bg.loc[fill, f.name] = tract[f.name].reindex(tract_of[fill]).to_numpy()
        bg.loc[fill, f"{f.name}_censored"] = tract[f"{f.name}_censored"].reindex(tract_of[fill]).to_numpy()

    land = gpd.read_file(f"zip://{TIGER_BG}", ignore_geometry=True)[["GEOID", "ALAND"]].set_index("GEOID")["ALAND"]
    bg["land_km2"] = (land.reindex(bg.index) / 1e6).where(lambda s: s > 0)
    bg["housing_density_km2"] = bg["housing_units"] / bg["land_km2"]

    cv = lambda n: (moe[n] / 1.645) / bg[n]
    bg["moe_pct_owner_sfd"] = moe["pct_owner_sfd"]
    bg["cv_median_hh_income"] = cv("median_hh_income").where(~bg["median_hh_income_from_tract"])
    bg["cv_median_home_value"] = cv("median_home_value").where(~bg["median_home_value_from_tract"])
    bg["no_households"] = ~has_hh
    bg["acs_low_confidence"] = (
        (bg["occupied_units"] < MIN_HOUSEHOLDS)
        | (bg["moe_pct_owner_sfd"] > LOW_CONF_SHARE_MOE)
        | (bg["cv_median_hh_income"] > LOW_CONF_MEDIAN_CV)
        | (bg["cv_median_home_value"] > LOW_CONF_MEDIAN_CV)
    )
    bg.insert(0, "acs_vintage", f"{vintage - 4}-{vintage}")
    return bg.reset_index()


# ---------------------------------------------------------------- checks
def checks(bg: pd.DataFrame, vintage: int) -> None:
    tiger = set(gpd.read_file(f"zip://{TIGER_BG}", ignore_geometry=True)["GEOID"])
    assert set(bg["GEOID"]) == tiger and bg["GEOID"].is_unique, "GEOIDs differ from TIGER 2020 block groups"
    print(f"rows: {len(bg):,} block groups, same GEOIDs as TIGER 2020")

    # block-group counts add up to their tract
    tr = pd.read_parquet(INTERIM / f"acs_{vintage}_tract.parquet").set_index("GEOID")["B25003_E001"]
    s = bg.groupby(bg["GEOID"].str[:11])["occupied_units"].sum()
    print(f"bg->tract occupied units match: {(s == tr.reindex(s.index)).mean():.1%} of tracts")

    tot = bg[["occupied_units", "eligible_homes"]].sum()
    print(f"Texas owner-occupied SFD share of households: {tot.eligible_homes / tot.occupied_units:.1%}; "
          f"low-confidence block groups: {bg['acs_low_confidence'].mean():.1%}; "
          f"no households: {bg['no_households'].sum()}")

    perm = pd.read_parquet(PROCESSED / "bg_permits.parquet")
    share = pd.read_parquet(PROCESSED / "bg_city_share.parquet")
    missing = set(perm["GEOID"]) - set(bg["GEOID"])
    print(f"permit block groups found in ACS: {1 - len(missing) / perm['GEOID'].nunique():.1%}")

    feats = [f.name for f in FEATURES if f.kind != "count"] + ["housing_density_km2"]
    city = bg["GEOID"].isin(share.loc[share["share_in_city"] >= 0.9, "GEOID"])
    miss = pd.DataFrame({"statewide": bg[feats].isna().mean(), "permit_cities": bg.loc[city, feats].isna().mean()})
    print("\nmissing rate (after tract fill):")
    print((miss * 100).round(1).to_string())

    # sanity: correlation with the backup-install rate inside the permit cities, 2021-2025
    lab = (perm[perm["year"].between(2021, 2025)].groupby("GEOID")["backup_install"].sum())
    d = bg[city].set_index("GEOID").join(lab.rename("backup"))
    d["backup"] = d["backup"].fillna(0)
    d = d[d["eligible_homes"] >= 50]
    d["rate"] = 1000 * d["backup"] / d["eligible_homes"]
    rho = d[feats].rank().corrwith(d["rate"].rank()).sort_values()  # Spearman without scipy
    print(f"\nSpearman vs backup installs per 1,000 eligible homes (2021-2025, {len(d):,} in-city block groups):")
    print(rho.round(2).to_string())


def write_doc(vintage: int) -> None:
    arrow = {1: "+", -1: "-", 0: ""}
    rows = [f"| `{f.name}` | {f.kind}{' (tract)' if f.tract_only else ''} | {' + '.join(f.num)}"
            + (f" / {' + '.join(f.den)}" if f.den else "") + f" | {arrow[f.direction]} | {f.desc} |"
            for f in FEATURES]
    DOC.write_text("\n".join([
        "# ACS block-group features",
        "",
        f"Generated by `acs/features.py` (ACS 5-year {vintage - 4}-{vintage}). Output: `data/processed/bg_acs_<vintage>.parquet`.",
        "Direction = expected effect on backup propensity, used as a monotone-constraint hint (blank = no prior).",
        "",
        "| Feature | Kind | ACS columns | Dir | Meaning |",
        "| --- | --- | --- | --- | --- |",
        *rows,
        "| `housing_density_km2` | derived | housing_units / TIGER ALAND | | Housing units per km² of land |",
        "",
        "Flags and quality columns (not model features):",
        "",
        "- `(tract)`: table not published for block groups; every block group gets its tract's value.",
        "- `<median>_censored`: median in an open-ended bin (e.g. home value 2,000,001 = $2M+, year built 1939 = 1939 or earlier).",
        "- `<median>_from_tract`: block-group median suppressed; tract value copied down.",
        "- `moe_pct_owner_sfd`, `cv_median_hh_income`, `cv_median_home_value`: 90% MOE / coefficient of variation.",
        f"- `acs_low_confidence`: < {MIN_HOUSEHOLDS} households, or MOE(pct_owner_sfd) > {LOW_CONF_SHARE_MOE:.0%} points,"
        f" or income / home-value CV > {LOW_CONF_MEDIAN_CV}.",
        "- `no_households`: no occupied units (parks, airports, water, institutions); shares are NaN.",
        "",
    ]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vintage", type=int, default=2024)
    args = ap.parse_args()
    bg = build(args.vintage)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    out = PROCESSED / f"bg_acs_{args.vintage}.parquet"
    bg.to_parquet(out, index=False)
    if args.vintage == REFERENCE_VINTAGE:
        write_doc(args.vintage)
    print(f"-> {out.relative_to(ROOT)} ({bg.shape[1]} columns)\n")
    checks(bg, args.vintage)


if __name__ == "__main__":
    main()
