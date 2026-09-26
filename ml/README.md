# ml

Data preparation for the ML model: labels and block-group features from public data.
Separate uv project from `apps/api`; nothing here runs in docker-compose.

## Setup

```bash
cd ml
uv sync
cp .env.example .env   # then set TYPESAFE_API_KEY
```

## Layout

| Path | What |
| --- | --- |
| `permits/fetch.py` | Step 1: pull Austin (Socrata), San Antonio (CSV), Fort Worth (ArcGIS, battery label only) permits → `data/interim/permits_all.parquet` |
| `permits/keywords.py` | Keyword prefilter and flags (generator / battery / solar / panel …) |
| `permits/questions.py` | The Jev questions (one per gold field) and the per-permit state |
| `permits/jev.py` | Runs Jev over permits with an answer cache; loads `ml/.env` |
| `permits/label.py` | Keyword baseline fields, Jev fields, and the `backup_install` label rule |
| `permits/gold.py` | Gold sample (300 permits, tune/test halves) and the labeling page |
| `permits/llm_label.py` | LLM pre-labels for the 300 gold permits only (hand review overrides) |
| `permits/build_label.py` | Label v1: install events, 180-day address dedup, 2020 block groups, city share |
| `permits/evaluate.py` | Keyword vs Jev accuracy against the gold labels |
| `parcels/fetch.py` | Appraisal-district parcels (polygons + home attributes) from county ArcGIS services → `data/interim/parcels_raw_{county}.parquet` |
| `parcels/normalize.py` | One schema per parcel (state code, home type, sq ft, year built, lot, value, owner-occupied, deed year) |
| `parcels/aggregate.py` | Parcels → 2020 block groups: eligible homes (label exposure), home features, installable share |
| `acs/variables.py` | ACS 5-year tables pulled and the Census summary-file URLs |
| `acs/fetch.py` | ACS step 1: download tables (no API key), keep Texas block groups + tracts → `data/interim/acs_<vintage>_{bg,tract}.parquet` |
| `acs/features.py` | ACS step 2: shares, medians, tract fill, MOE / low-confidence flags → `data/processed/bg_acs_<vintage>.parquet` |
| `acs/ANALYSIS.md` | ACS data analysis: validation, missingness, MOE, vintage differences, first look at the label |
| `acs/FEATURES.md` | Generated data dictionary for `bg_acs_<vintage>.parquet` |
| `train/build_table.py` | Joins label + ACS + parcels → `data/processed/train_bg.parquet` (one row per training block group) |
| `train/model.py` | Propensity v1: LightGBM Poisson, per-city offset, spatial / temporal / leave-one-city-out evaluation |
| `train/baselines.py` | Income / home value / past-installs baselines, scored within city on 2024-2025 installs |
| `docs/typesafe/` | Jev docs snapshot (SDK, primitives, confidence, jev-1.13 limits) |
| `data/` | Git-ignored. `raw/` downloads, `interim/` normalized tables, `gold/` labels, `processed/` outputs |

## Run

```bash
uv run python -m permits.fetch                   # 1. permits -> data/interim/permits_all.parquet
uv run python -m permits.gold sample              # 2. draw the gold sample
uv run python -m permits.llm_label --effort high  # 3. LLM pre-labels (OPENAI_* in .env)
uv run python -m permits.jev --input data/gold/gold.csv --output data/gold/gold_jev.parquet
uv run python -m permits.gold serve               # 4. review disagreements at http://localhost:8765/?review=1
uv run python -m permits.evaluate --split tune    # 5. tune on "tune", quote "test"
uv run python -m permits.jev --input data/interim/permits_all.parquet --output data/interim/permits_jev.parquet
uv run python -m permits.build_label              # 6. label v1 -> data/processed/
uv run python -m parcels.fetch                    # 7. Travis + Bexar parcels (~20 min, resumable)
                                                  #    DFW: StratMap zips by hand, see Parcel checks
uv run python -m parcels.normalize
uv run python -m parcels.aggregate                # 8. -> data/processed/bg_parcels.parquet
```

ACS block-group features (join to `bg_permits.parquet` on `GEOID`):

```bash
uv run python -m acs.fetch --vintage 2024      # ~30 s, cached in data/raw/acs/2024/
uv run python -m acs.features --vintage 2024   # -> data/processed/bg_acs_2024.parquet + checks
```

Training table and baselines (after the three pipelines above):

```bash
uv run python -m train.build_table   # -> data/processed/train_bg.parquet + checks
uv run python -m train.baselines
uv run python -m train.model         # ~35 s -> data/processed/model_v1*.txt, train_bg_oof.parquet
```

LightGBM on macOS needs OpenMP: `brew install libomp`.

ACS comes from the Census table-based summary files, not api.census.gov (which now requires a key).
`--vintage 2024` = ACS 2020-2024 on 2020 block groups. `--vintage 2021` (2017-2021, same block groups)
is for temporal validation; `features.py` stops if a table's line labels changed between vintages. See `acs/FEATURES.md` for every column.

Jev answers are cached in `data/interim/jev_cache.jsonl`, keyed by question version, model,
and permit text. Bump `QUESTIONS_VERSION` in `permits/questions.py` when wording changes.

Jev answers bounded yes/no and pick-one questions about permit text. Numbers (kW, amps,
kWh), dates, dedup, and label rules stay in code. No per-permit LLM calls.

## Label accuracy (gold test half, n=154)

Gold = gpt-6-astra labels, 6 luna/astra disagreements adjudicated (`data/gold/labels.csv`).
gpt-6-luna and gpt-6-astra agree on 98% of backup-install labels.

| backup_install | accuracy | precision | recall |
| --- | --- | --- | --- |
| keywords (v0) | 92.2% | 85.4% | 85.4% |
| Jev (v1) | 92.9% | 89.5% | 82.9% |

Label rule (`permits/label.py`): standby generator or battery, action is a new install / add to
existing / can't tell, property is single-family or can't tell, and not a plumbing/gas permit.

## Parcel checks (6 counties, 3.3M parcels, 5,890 block groups, vs ACS 2020-2024)

| county | source | eligible homes vs ACS: corr / median ratio | year built vs ACS: corr |
| --- | --- | --- | --- |
| Bexar | county GIS service | 0.93 / 0.95 | 0.87 |
| Travis | county GIS service | 0.80 / 0.83 | 0.70 |
| Collin | TxGIO StratMap 2025 | 0.92 / 1.00 | 0.88 |
| Dallas | TxGIO StratMap 2025 | 0.89 / 0.96 | no year built in file |
| Denton | TxGIO StratMap 2025 | 0.84 / 0.95 | 0.84 |
| Tarrant | TxGIO StratMap 2025 | 0.90 / 1.04 | 0.84 |

Eligible homes = single-family detached + owner-occupied. Owner-occupied = Bexar HS exemption code;
elsewhere mailing address = property address. Backup-install permits land on single-family parcels
90% (Austin) / 93% (San Antonio) of the time, and those homes are 90-93% owner-occupied vs 68-77%
for all single-family homes. Living sq ft only in Bexar; deed year only in Travis.
`installable_share` has no footprint/open-space rule yet, so outside Austin it is close to the
single-family share.

StratMap zips (`data/raw/parcels/stratmap25-landparcels_{fips}_lp.zip`) must be downloaded in a
browser from the TxGIO DataHub: its CDN answers 403 to scripted requests.

## Training table (`train_bg.parquet`)

- **Rows:** 1,313 block groups ≥ 90% inside Austin (462) or San Antonio (851), with eligible homes > 0
  (133 dropped). Permits only cover city limits, so block groups straddling the boundary would undercount.
- **Label:** `y` = backup installs 2021-2025 (3,029). Per-year `y_2021`…`y_2025`, `y_2021_2023` / `y_2024_2025`
  for the temporal split, `y_no_uri` without 2021. 2026 is partial; San Antonio data starts Dec 2020.
- **Exposure:** ACS `eligible_homes`. Parcel `parcel_n_eligible_homes` agrees (corr 0.90, median ratio 0.92).
- **Features:** 24 ACS columns (`train.build_table.acs_features`): meta, censoring / tract-fill flags and the three
  unstable ACS features are left out. `parcel_*` columns are carried for the installable multiplier and sensitivity
  checks only: sq ft (Bexar) and deed year (Travis) exist in one county each, so with two training cities they
  would stand in for the city. `aux_*` are other permit counts (solar, panel, Base Power…), never features.
- **City gap:** 17.7 installs per 1,000 eligible homes in Austin vs 2.5 in San Antonio. Part is likely permit
  practice, not demand, so the model needs a city offset and propensity is ranked within metro.

Baselines, within city, 2024-2025 installs (capture@k = share of installs in the top k% of block groups by
score; Spearman on install rate, block groups with ≥ 50 eligible homes):

| | Austin capture@20 | Austin Spearman | San Antonio capture@20 | San Antonio Spearman |
| --- | --- | --- | --- | --- |
| income only | 46% | 0.37 | 58% | 0.33 |
| home value only | 45% | 0.53 | 67% | 0.37 |
| past installs 2021-23 (rate) | 44% | 0.56 | 59% | 0.34 |
| random | 18% | 0.04 | 22% | 0.02 |

## Propensity model v1 (`train/model.py`)

LightGBM Poisson on the 24 ACS features, and a Poisson GLM on 7 (log home value, log income, log density,
single-family share, 65+ share, owner household size, WFH share) as the "are trees worth it" check. Offset =
log(exposure) + log(city install rate): both rank block groups *within* a city. Exposure = parcel eligible homes
(ACS × 0.92 where no parcels). Spatial CV folds are 5 km grid cells.

Metrics (`train/baselines.py`): **capture AUC** is the count version of ROC AUC (x = share of eligible homes,
best score first; y = share of installs; 0.5 random, 1 perfect). **homes@20** = share of installs in the top 20%
of eligible homes. A plain ROC AUC on "block group had ≥ 1 install" is misleading here: it rewards big block groups.

Spatial CV × time (train 2021-2023 on 4/5 of the blocks, rank the held-out fifth, 2024-2025 installs):

| | Austin capture AUC / homes@20 | San Antonio capture AUC / homes@20 |
| --- | --- | --- |
| LightGBM | 0.68 / 45% | 0.77 / 60% |
| GLM (7 features) | 0.68 / 44% | 0.77 / 58% |
| home value only | 0.69 / 44% | 0.77 / 59% |
| past installs 2021-23 | 0.69 / 46% | 0.71 / 55% |
| income only | 0.62 / 33% | 0.70 / 47% |
| random | 0.50 / 20% | 0.50 / 20% |

Leave one city out (2021-2025), capture AUC: LightGBM 0.62 (Austin) / 0.71 (San Antonio), **GLM 0.69 / 0.76**,
home value 0.68 / 0.75.

- **The signal is real and useful**: the top 20% of homes by score hold 44-60% of installs, 2.2-3× random.
  Ranking areas from Census data alone does as well as knowing where installs already happened.
- **No model beats home value on its own yet.** Both models tie it inside a city.
- **LightGBM does not transfer between cities; the GLM does.** For scoring metros with no permits (DFW) the GLM
  is the safer choice today. Coefficients (per sd, log-rate): home value +0.61, 65+ +0.26, income +0.21,
  density −0.14, single-family share −0.30.
- **Parcel exposure fixed most of the spurious owner-occupied-SFD effect** (ACS undercounts eligible homes in mixed
  block groups). A negative single-family *share* remains; unexplained, possibly installs on homes the label
  counts as "can't tell" property type.
- **Fort Worth (validation city, never trained on).** Fetched from the city's ArcGIS points layer
  (`permits.fetch --cities fort_worth`). Only building permits carry descriptions, so generators are invisible:
  9 in 2021-2025 vs 686 batteries in the table rows. 97% of its battery permits are bundled with solar. Nothing
  ranks them, not the models and not home value (capture AUC 0.50-0.54). Their drivers are a solar-buyer profile
  (newer, mortgaged, middle-income homes: year built ρ 0.27, mortgage 0.25, home value 0.14), whereas generators
  follow wealth (Austin home value ρ 0.55). **Solar + storage is a different buyer from backup power**, so Fort
  Worth cannot validate the backup model; it would need its trade permits.
- **Base Power 2026 check is circular.** 229 Base Power permits (Austin, 2026) land where the model and home value
  point (capture AUC 0.69 / 0.68), but Base reportedly targets by a home-value table, so this mostly measures
  Base's own targeting. Not evidence for the model.
- **Nothing beyond home value yet.** Model vs home-value rank correlation 0.75, two-thirds of the top-20% block
  groups shared. Within home-value quintiles the model still ranks above random (capture AUC 0.57 Austin, 0.62
  San Antonio), but a 50/50 rank blend with home value gains only +0.005-0.012 AUC. Block-group ACS features
  cannot beat a home-value rule; the next test is home-level (parcel) features against per-home value.
- **Label fix:** permits at the same address and date were deduplicated in unstable sort order, so adding rows
  could swap a built permit for a withdrawn one. Ties now keep the built permit (Austin 2021-2025: +25 installs).
