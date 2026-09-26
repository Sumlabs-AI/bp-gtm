# ML contract: Need Engine ↔ Propensity model

The one page the ML workstream needs. Both sides join on **H3 resolution-8 `h3_index`** (see `app/geo`, or any H3 library at resolution 8). Terms: [`CONTEXT.md`](../CONTEXT.md).

## Big picture

```text
                           GTM ENGINE
                               │
              ┌────────────────┴────────────────┐
              │                                 │
       DETERMINISTIC ENGINE                ML ENGINE
       (this repo, Need)                   (Propensity)
              │                                 │
              │                           Permit history
              ▼                                 ▼
       H3 RES-8 CELL ◄────────────────── H3 RES-8 CELL
              │
      ┌───────┴────────┐
      │                │
 HISTORICAL DATA    GEOGRAPHY
      │            county_fips, load_zone, center lat/lng, H3 res-6 parent
      ├── OUTAGE   outage hours/customer, major events, peak customers out, utility SAIDI
      │            → Observed Outage Exposure, Utility Reliability Need, Outage Need
      └── WEATHER  storm warning-days, ≥100°F days, ≤28°F days
                   → Storm Exposure, Temperature Extremes, Weather Need
              │
              ▼
        BASELINE NEED
              │
              ├── need_features.parquet        (res 8, product Cells)
              └── need_reference_res6.parquet  (res 6, statewide reference)
                         │
                         ▼
                  PROPENSITY MODEL  (permit history + static features)
                         │
                  propensity.parquet: h3_index (res 8), propensity_score 0–100,
                                      model_version, feature_version, scored_at
                         │
                         ▼
                  NEED ENGINE API
             ┌───────────┼────────────┐
             ▼           ▼            ▼
         BASELINE    PROPENSITY    LIVE SIGNALS (NWS Alerts, Forecast, ERCOT Condition, Grid Stress)
           NEED
             └───────────┼────────────┘
                         ▼
                   GTM OPPORTUNITY (later; not defined yet)
```

**The rule that matters most:** the Propensity model receives **static/historical features only**. Live weather and ERCOT signals are activation signals that change hour to hour; they are **not** training features (a permit issued in 2023 must not be explained by today's heat forecast). They're combined downstream with Baseline Need and Propensity to make GTM Opportunity.

## Three scores, kept apart

```text
BASELINE NEED   "Would a battery be structurally useful here?"      (this repo)
PROPENSITY      "Who is likely to buy?"                             (ML workstream)
LIVE NEED       "Why now?"                                          (this repo, later)
                          └──────────► GTM OPPORTUNITY "Who should Base target now?" (later)
```

## Input to ML: `need_features.parquet`

- **Grain:** 1 row = 1 H3 res-8 Cell (currently 8,715: Harris and Travis counties). **Key:** `h3_index`.
- Static. No live columns. Missing values are **null, never 0**.
- Produced by `python -m app.need export-ml --out-dir data/ml` (also writes the reference file below). Typed Parquet (zstd), ~150 KB.

| Column | Type | Meaning |
| --- | --- | --- |
| `h3_index`, `resolution` (8), `center_lat`, `center_lng`, `h3_res6` | | identity and geometry; `h3_res6` is the res-6 parent (storm grain) |
| `county_fips`, `load_zone` | | Census county; ERCOT Load Zone (null for 95 edge Cells) |
| `outage_hours_per_customer_5y`, `outage_events_5y`, `major_outage_events_5y`, `peak_customers_out_pct_5y`, `outage_hours_per_customer_365d` | double/int | EAGLE-I county outage history (county grain) |
| `utility_id`, `utility_saidi_wo_med_5y`, `utility_saifi_wo_med_5y` | | EIA-861 reliability of the Cell's utility (null where the utility is unknown) |
| `storm_warning_days_5y`, `severe_thunderstorm_warnings_5y`, `tornado_warnings_5y` | int | NWS warning-days at the res-6 parent |
| `heat_days_100f_5y`, `heat_days_95f_5y`, `cold_days_28f_5y`, `cold_days_32f_5y` | int | measured county temperature days (dry-bulb) |
| `observed_outage_exposure`, `utility_reliability_need`, `outage_need` | double | Outage sub-scores and component (Texas percentiles) |
| `storm_exposure`, `temperature_extremes_exposure`, `weather_need` | double | Weather sub-scores and component |
| `baseline_need_raw`, `baseline_need`, `dominant_driver` | | union-style combination, its Texas res-6 percentile, and `outage` / `weather` / `both` |
| `outage_data_through`, `utility_data_through_year`, `storm_data_through`, `temperature_data_through` | date/int | how far each source's history runs |
| `feature_version`, `exported_at` | | see below |

Details of every feature: [need-engine.md](need-engine.md).

## Also provided: `need_reference_res6.parquet`

- **Different grain and purpose.** 1 row = 1 Texas H3 **res-6** cell (~36 km², 16,697 rows): the statewide reference Baseline Need is ranked against. Useful as Texas-wide training context if permits exist beyond Harris/Travis.
- Same feature definitions as above (county features via the cell center's county), plus `baseline_need_raw`. There's **no `baseline_need`** column: the reference is what Cells are ranked against, not ranked itself.
- **Production predictions are res 8.** Don't hand back res-6 predictions.

## Output from ML: `propensity.parquet`

- **Grain:** 1 row = 1 res-8 Cell prediction.

| Column | Type | Rule |
| --- | --- | --- |
| `h3_index` | string | valid H3, **resolution 8** |
| `propensity_score` | double | **strictly 0–100**. Convert probabilities before export; the import does not auto-detect 0–1. |
| `model_version` | string | your model identifier |
| `feature_version` | string | the Need Feature Version you trained/scored against (from the export) |
| `scored_at` | timestamp | model prediction time |

- Extra columns are ignored.
- **The whole file is rejected** (nothing stored) if any row has an invalid or non-res-8 `h3_index`, a score outside 0–100, or a missing required column. The report names the first offending rows.
- Predictions for valid res-8 Cells we haven't seeded are accepted and counted separately.
- A `feature_version` other than the current one is accepted with a warning.
- Load: `python -m app.need import-propensity propensity.parquet`. History is kept (`cell_propensities`); the API serves the **latest `scored_at`** per Cell and names its `model_version`. `imported_at` is recorded separately.

Meaning: Propensity = likelihood/affinity for battery adoption. It is **not** Need and **not** GTM Opportunity. The API shows it beside Baseline Need (`GET /need/cells/{h3}` → `propensity`, map features → `propensityScore`) and never combines the two here.

## Feature Version changelog

| `feature_version` | Definitions |
| --- | --- |
| **1.0.0** | Outage: EAGLE-I 2021–2025 events (0.1% threshold, 1 h merge, major ≥ 5% or ≥ 1 h/customer), EIA-861 2020–2024 5-year SAIDI w/o MED. Weather: SV/TO/EW warning-days on res 6, nClimGrid ≥100°F / ≤28°F county days (dry-bulb). Baseline: soft-OR of Observed Outage Exposure and Weather Need, Texas res-6 midrank percentile. |

Bump the version (`FEATURE_VERSION` in `app/need/config.py`) whenever a definition, threshold, window or source changes, and add a row here.

## Known limitations of the features
- Temperature is dry-bulb (no humidity/heat index): humid heat, e.g. Houston, is under-rated (backlog #21).
- Outage features are county-level.
- Utility reliability is known only for CenterPoint (Harris) and Austin Energy (LZ_AEN).
