# GTM datasets v1 (2026-09-26)

> **Copyright (c) 2026 Igor Eduardo.** Produced by Igor Eduardo for his hackathon team.
> **Team:** hackathon team members may use these datasets freely for the team's project.
> **Sponsor and third parties:** the hackathon sponsor (and its affiliates) or anyone else needs a
> written license from Igor Eduardo for any use, including after the hackathon. See [`LICENSE.txt`](LICENSE.txt).

## Download

The files are attached to the release, not committed (about 260 MB):
https://github.com/mamalovesyou/bp-gtm/releases/tag/datasets-v1

```bash
gh release download datasets-v1 -R mamalovesyou/bp-gtm -D datasets/files
```

Data-map layers for GTM: **Fit** (Census ACS, every Texas block group), **Need** (HHS emPOWER
electricity-dependent Medicare population) and **Home / installability** (Travis County parcels).
All files are Parquet (GeoParquet, EPSG:4326, when they have a `geometry` column) unless noted.
Join key across layers: `geoid` / `bg_geoid` = 12-digit block-group GEOID (string, keep leading
zeros). Parcel files join on the Travis Central Appraisal District property id (`PROP_ID` / `prop_id`).

## Files

| File | Rows | Level | Contents |
| --- | ---: | --- | --- |
| `fit_features_TX_bg_acs2024.parquet` (also `.csv.gz`) | 18,638 | Block group, Texas | 26 Fit features, each with `_moe`, `_cv`, `_rel` (high / medium / low) and `_rel_reason` when reliability is unavailable; context counts; `owner_sfd_units`; `owner_electric_heat_pct_tract` |
| `fit_features_Travis_bg_acs2024.csv` | 766 | Block group, Travis | Travis subset of the file above |
| `fit_features_data_dictionary.csv` | 29 | — | Every feature: ACS table, cells, universe, notes, coverage, Texas and Travis medians |
| `fit_features_TX_bg_acs2024_eb.parquet` | 18,638 | Block group, Texas | Stabilized version of each feature (`<feature>_eb`), its weight on the block group's own estimate (`_eb_w`), its source (`_eb_src`) and reference value (`_eb_target`) |
| `fit_features_TX_tract_acs2024.parquet` | 6,896 | Tract, Texas | The same features at tract level |
| `fit_features_TX_bg_acs2024_geo.parquet` | 18,626 | Block group, Texas | Features + stabilized features on block-group polygons, with `ALAND`, `AWATER`, `hh_per_km2` |
| `empower_TX_zip.parquet` | 1,850 | ZIP, Texas | HHS emPOWER counts per ZIP (polygons), with `<count>_masked` flags |
| `empower_TX_bg.parquet` | 18,626 | Block group, Texas | emPOWER counts allocated to block groups (`*_bg_alloc`), `dominant_zip`, `dme_per_1k_medicare`, `dme_per_1k_owner_sfd`, `any_service_per_1k_medicare` |
| `travis_parcels_installability.parquet` | 373,524 | Parcel, Travis | County appraisal parcels with footprints, installability gates and block group |
| `travis_bg_parcel_aggregates.csv` | 766 | Block group, Travis | Parcel counts and medians per block group, next to the ACS owner-occupied single-family count |
| `travis_parcels_clean_part1.parquet` + `_part2.parquet` | 380,917 | Parcel, Travis | StratMap 2025 parcels, cleaned and deduplicated, with polygons (split in two files; read both and concatenate) |
| `household_install_table.parquet` (+ `household_install_table_dictionary.csv`) | 373,524 | Parcel, Travis | One row per parcel: market value, eligibility gates, and whether the home has a permitted backup-power install (generator, battery, Base Power), with first install date and install event counts |

## Column notes

**Fit features** (`fit_features_*`): see `fit_features_data_dictionary.csv`. Proportions are on a
0–1 scale despite the `_pct` suffix. Reliability: `_rel` = high (CV < 12%), medium (12–40%), low
(> 40%); year medians use the MOE in years (≤ 5 / ≤ 15 / > 15). `_rel_reason` = `zero_estimate`,
`no_moe` or `no_estimate`. Flags: `flag_home_value_topcoded` (≥ $2,000,001),
`flag_income_topcoded` (≥ $250,001), `flag_year_built_bottomcoded` (≤ 1939), `flag_small_universe`
(< 50 occupied units). `owner_electric_heat_pct_tract` is a tract value repeated on each of its
block groups (the source table is not published at block group).

**Stabilized features** (`_eb` file): `_eb_src` = `eb` (stabilized), `raw` or `raw_single_bg` (the
block group's own estimate), `tract_fill` (block group estimate missing, reference value used),
`no_universe` (nobody in the universe: left empty), `missing`. Prefer `_eb` over the raw estimate
for noisy features (vacancy, work from home, cost burden, household size). Use
`single_family_attached_pct` at tract level only. Because stabilized values borrow from the tract,
validate models with folds grouped by tract or county.

**emPOWER**: counts of 1–10 are suppressed by the source and published as 11; `_masked = True`
means "between 1 and 11". Medicare fee-for-service and Medicare Advantage beneficiaries.
Area-level signal only: never use it to single out a household.

**Travis parcels** (`travis_parcels_installability`): `land_state_cd` = Texas property class (A1
single-family, E1 farm/ranch with residence, …); `homesite_class` = homesite value > 0 (a use
class, not the homestead exemption); `mail_matches_situs` = owner mailing address is the property
address (1/0, empty when unknown). Gates: `g_sfr` (A1 or E1), `g_owner_proxy`
(`mail_matches_situs` = 1), `g_has_structure` (building footprint or year built), `g_detached_lot`
(lot ≥ 2,500 sq ft). `installable` = all four gates; `installable_relaxed` = all but the owner
proxy (216,768 and 286,084 parcels). Footprint columns: `n_buildings`, `n_residential_bldg`,
`fp_main_sqft`, `fp_total_sqft`, `fp_coverage`, `open_lot_sqft`. Areas in sq ft.

**Household install table** (`household_install_table`): one row per TCAD parcel (same
parcels and gates as `travis_parcels_installability`), keyed by `prop_id`. `has_generator`,
`has_battery`, `has_base_power`, `has_backup_install` (any of them) and `first_*_date` come from
City of Austin issued permits matched to the parcel; `has_base_power_2026` = Base Power permit
issued in 2026. `n_*_events` = distinct installation events (`n_backup_events_90d` with a 90-day
window). `match_method_best` / `match_confidence_best` describe the permit-to-parcel match.
Variants: `*_hc` = high-confidence matches only; `*_broad` = broader backup definition (adds other
backup equipment and replacements). `in_coa_entity02` = parcel taxed by the City of Austin (the
permit source covers City of Austin jurisdiction only, so homes outside it show no permits).
`acs_bg_median_home_value` = ACS median home value of the parcel's block group. Totals: 5,278
homes with a backup install, 3,179 generator, 2,166 battery, 302 Base Power 2026.

**StratMap parcels** (`travis_parcels_clean_part*`): one row per `prop_id`; `n_accounts` = appraisal
accounts on the parcel; `lot_sqft`, `lot_acres` (and `lot_acres_3083`, equal-area) from the polygon;
`bg_outside_travis` = 1 for the 635 border parcels whose point falls in a neighbouring county's
block group; `tcad_land_state_cd` / `tcad_installable` from the county parcel file above
(373,406 parcels in both). The source's `GIS_AREA` field is not used (about 10.8× too large).

No file contains owner names or mailing addresses.

## Sources

| Layer | Source | Publisher | Access |
| --- | --- | --- | --- |
| Fit features | American Community Survey 2020–2024 5-Year, table-based summary files: tables B01003, B08301, B11005, B11007, B11016, B19013, B25002, B25003, B25010, B25018, B25024, B25032, B25035, B25038, B25039, B25040, B25041, B25077, B25081, B25117, B25140 — https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/ (`data/5YRData/acsdt5y2024-<table>.dat`, `documentation/Geos20245YR.txt`, `documentation/ACS20245YR_Table_Shells.txt`) | U.S. Census Bureau | Public, no key |
| Block-group polygons | 2024 Cartographic Boundary File, Texas block groups, 1:500,000 — https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_48_bg_500k.zip | U.S. Census Bureau | Public |
| emPOWER | HHS emPOWER REST Service, "Electricity Dependent DME – ALL – ZipLevel" — https://services2.arcgis.com/ZQ4jTQn6k7VPXEwO/arcgis/rest/services/HHS_emPOWER_REST_Service_Public/FeatureServer/1 (program: https://empowerprogram.hhs.gov) | HHS ASPR with CMS | Public, aggregated |
| Travis parcels | TCAD parcels — https://gis.traviscountytx.gov/server1/rest/services/Boundaries_and_Jurisdictions/TCAD/MapServer/0 | Travis County / Travis Central Appraisal District | Public GIS service |
| Building footprints | Building Footprints 2024 — https://gis.traviscountytx.gov/server1/rest/services/Basemap_Reference/Building_Footprints_2024/MapServer/0 | Travis County | Public GIS service |
| Backup-power permits | City of Austin Issued Construction Permits — https://data.austintexas.gov/resource/3syk-w9eu (dataset updated 2026-09-26) | City of Austin | Public open data |
| StratMap parcels | StratMap 2025 Land Parcels, Travis County (48453), `stratmap25-landparcels_48453_lp.zip` — TxGIO DataHub, https://data.geographic.texas.gov/ (service: https://feature.tnris.org/arcgis/rest/services/Parcels/stratmap25_land_parcels_48/MapServer) | Texas Geographic Information Office (TxGIO), from the Travis Central Appraisal District, Aug 2025 | Public download |

Retrieved 2026-09-26 (permits: 2026-09-27).

## Compliance

| Topic | Statement |
| --- | --- |
| Ownership | Copyright (c) 2026 Igor Eduardo. The datasets are his original work, produced for his hackathon team. |
| License | Free use by the hackathon team members for the team's project. The hackathon sponsor, its affiliates and any third party need a written license signed by Igor Eduardo for any use ([`LICENSE.txt`](LICENSE.txt)). |
| Provenance | Built only from the public sources listed above, through their official downloads and public services, retrieved 2026-09-26. No login-protected, paid or non-commercial source (e.g. utility outage maps) was used. |
| Source terms | Census Bureau and HHS data are U.S. Government public data. Travis County GIS and TxGIO StratMap data stay subject to their publishers' terms. The copyright covers the datasets as produced and compiled, not the original source records. |
| Personal data | No owner names, owner IDs or mailing addresses in any file. Install flags come from public permits and describe properties, not people; do not combine them with other data to identify residents. The owner-occupancy flag is computed without storing the mailing address. |
| Health data | emPOWER counts are aggregated and suppressed by the source (1–10 published as 11). Use them only as an area-level signal, never to single out a household or person. |
| Accuracy | Screening estimates, provided "as is" without warranty. ACS block-group values carry sampling error: keep the MOE / reliability or use the `_eb` columns. |
| In-file notice | Every Parquet file carries this copyright, license and source notice in its metadata (`copyright`, `license`, `sources`, `compliance` keys). |
