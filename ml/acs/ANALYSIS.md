# ACS block-group features: data analysis

Checks and findings for `data/processed/bg_acs_<vintage>.parquet` (built by `acs/fetch.py` + `acs/features.py`).
Column definitions: [`FEATURES.md`](FEATURES.md). Numbers below are from ACS 2020-2024 unless stated; run date 2026-09-26.

## Source and scope

- Census **table-based summary files** (one national file per table, estimates + MOEs), not api.census.gov,
  which now rejects requests without a key. 24 tables, ~30 s download, 48 MB cached (Texas rows only).
- Two vintages built, both tabulated on **2020 block groups** (same 18,638 GEOIDs as `tl_2020_48_bg`):
  - `2024` = ACS 2020-2024, the main feature set.
  - `2021` = ACS 2017-2021, for temporal validation (train ≤ 2023, predict 2024-2025).
- 6,896 tracts pulled alongside, used to fill suppressed block-group medians and for the tract-only table (B25117).

## Validation

| Check | Result |
| --- | --- |
| Rows vs TIGER 2020 block groups | 18,638 = 18,638, identical GEOID sets (both vintages) |
| Permit block groups (`bg_permits.parquet`) found in ACS | 100% |
| Independent source: Census Reporter API, 30 random block groups x 8 tables | 2,280 / 2,280 values match |
| Hand recompute (480019501001): `pct_owner_sfd`, its MOE, `pct_built_pre1980` | exact match |
| Block groups sum to their tract (occupied units) | 100% of tracts |
| Shared universes agree (B25032 = B25040 = B25003 totals; B25002 = B25001) | 100% of block groups |
| `eligible_homes` ≤ owner-occupied units | 100% |
| Shares outside [0, 1] | 0 |
| Tract-filled medians equal the tract value | 100% |

Texas-wide sanity: owner-occupied single-family detached homes are **55.4%** of households.

## Data quality

**Census annotation codes.** Estimates ≤ -111,111,111 (e.g. -666666666 "not computed") become NaN.
MOE -555555555 (controlled) is treated as 0; MOE -333333333 marks a median in an open-ended bin → `<median>_censored`.

**Suppressed medians at block-group level** (before tract fill → after):

| Median | Missing before | After tract fill |
| --- | --- | --- |
| `median_home_value` | 13.9% | 4.2% |
| `median_hh_income` | 9.0% | 1.1% |
| `median_year_moved_owner` | 8.8% | 3.4% |
| `median_owner_cost_pct` | 8.5% | 3.3% |
| `avg_hh_size_owner` | 6.3% | 2.7% |

Remaining NaNs are left for LightGBM (native missing handling). Shares are ~1% missing statewide
(0.3-0.4% in permit cities): 186 block groups have no households (parks, airports, water, institutions).
Owner-based shares (moved-in, mortgage, cost burden) are 5.5% missing: block groups with no owners.

**Top/bottom-coded medians** (flagged `_censored`): home value $2M+ (32 block groups), income $250k+ (222),
year built "1939 or earlier", median rooms 10+ (468), owner costs 50%+ of income.

**Tract-only table.** B25117 (heating fuel by tenure) is not published for block groups; every block group
gets its tract's `pct_owner_heat_electric`.

**Low confidence.** Block-group ACS is noisy everywhere. `acs_low_confidence` = fewer than 50 households, or
90% MOE of `pct_owner_sfd` > 25 points, or income / home-value CV > 0.5. That flags **16.8%** (2024) and 16.1% (2021).
Stricter thresholds (20 points / 0.4) would flag ~32%.

| MOE / CV distribution | median | 75th pct |
| --- | --- | --- |
| 90% MOE of `pct_owner_sfd` (points) | 12.8 | 18.4 |
| CV of median income | 0.22 | 0.32 |
| CV of median home value | 0.11 | 0.21 |

## Vintage differences (why `features.py` has a label guard)

ACS moves some category brackets with the survey years. Comparing the table shells of 2021-2023 with 2024
for every line a feature reads:

- **B25038** moved-in brackets: lines 003-004 are "2020+" in 2024, "2018+" in 2022-2023, "2015+" in 2021.
  The feature is named `pct_owner_moved_recent` for that reason. Lines 006-008 (before 2010) are stable.
- **B19013** income is in each vintage's own dollars: compare across vintages by rank, not level.
- All other lines used (year built, bedrooms, units in structure, heating fuel, cost burden, ...) are identical.

`check_line_labels` stops the build if any other line's label differs from the 2024 reference, so a new
vintage can't silently shift a feature's meaning.

## Stability across vintages

Spearman rank correlation of each feature between 2017-2021 and 2020-2024, excluding low-confidence block groups.
The two surveys share 2020-2021 responses, so these numbers flatter stability; low values mean mostly sampling noise.

| Feature | ρ | | Feature | ρ |
| --- | --- | --- | --- | --- |
| `pct_built_pre1980` | 0.93 | | `pct_hh_65plus` | 0.75 |
| `pct_sfd` | 0.93 | | `pct_owner_mortgage` | 0.70 |
| `median_home_value` | 0.92 | | `pct_hh_children` | 0.68 |
| `median_year_built` | 0.92 | | `pct_wfh` | 0.67 |
| `pct_heat_gas` | 0.91 | | `pct_owner_moved_pre2010` | 0.66 |
| `pct_owner_heat_electric` | 0.91 | | `median_year_moved_owner` | 0.64 |
| `pct_owner_sfd` | 0.90 | | `avg_hh_size_owner` | 0.64 |
| `median_rooms` | 0.89 | | `pct_vacant` | 0.62 |
| `pct_heat_electric` | 0.89 | | `pct_seasonal` | 0.62 |
| `pct_owner` | 0.88 | | `median_owner_cost_pct` | 0.46 |
| `pct_4plus_bedrooms` | 0.84 | | `pct_owner_cost_burdened` | 0.40 |
| `median_hh_income` | 0.84 | | `pct_owner_moved_recent` | 0.31 |
| `pct_mobile_home` | 0.83 | | | |

**Recommendation:** drop or deprioritize the bottom three when trimming to 20-40 features.

## First look at the label

Spearman correlation with backup installs per 1,000 eligible homes, 2021-2025, 1,230 block groups ≥ 90% inside
Austin or San Antonio with ≥ 50 eligible homes. Exploratory only (pooled across cities, no city effects).

| Positive | ρ | Negative | ρ |
| --- | --- | --- | --- |
| `median_home_value` | 0.70 | `pct_owner_heat_electric` | -0.39 |
| `median_hh_income` | 0.57 | `pct_owner_moved_pre2010` | -0.30 |
| `pct_wfh` | 0.55 | `avg_hh_size_owner` | -0.30 |
| `median_year_moved_owner` | 0.31 | `pct_heat_electric` | -0.29 |
| `pct_heat_gas` | 0.29 | `pct_built_pre1980` | -0.27 |
| `pct_owner_mortgage` | 0.26 | `pct_hh_children` | -0.18 |
| `median_year_built` | 0.25 | `pct_vacant` | -0.16 |
| `pct_4plus_bedrooms` | 0.25 | | |

Takeaways:

- **Wealth dominates.** Home value alone reaches ρ = 0.70, so the income-only baseline (and a home-value
  baseline) will be hard to beat. Report the lift over them honestly (plan risk #2).
- **Electric heat is negative**, against the "winter outage pain" hypothesis. Likely confounded: in these
  cities electric heat goes with older, cheaper, rental-heavy housing, and a standby generator needs a gas line.
  Worth checking once income is controlled for (SHAP dependence, or partial correlation).
- `pct_owner_sfd` ≈ 0: expected, since the rate is already per owner-occupied single-family home.
- `pct_wfh` is strong but also tracks income; check its effect after income.

## Open items

- Direction hints in `FEATURES.md` are priors only; confirm with partial dependence before turning them into
  LightGBM monotone constraints.
- Consider weighting training rows by `1 - acs_low_confidence` or by `eligible_homes` (Poisson exposure already
  does part of this).
- Distance to city center (TIGER geometry) is not built yet; `housing_density_km2` is.
