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
| `permits/fetch.py` | Step 1: pull Austin (Socrata) + San Antonio (CSV) permits → `data/interim/permits_all.parquet` |
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
