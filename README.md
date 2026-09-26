# base-power-gtm

**Base Radar** turns public data into a go-to-market map for [Base Power](https://basepowercompany.com):
where a home battery is structurally *needed*, where it is *likely to be bought*, and
where something is happening *right now* that makes it urgent.

- **Leads** (`/leads`, the home page): single-family, owner-occupied homes Base can serve
  (Harris County pilot), ranked by priority value, with the suggested battery size, talking
  points and a map. Refreshed weekly. See [wiki/residential-leads.md](wiki/residential-leads.md).
- **Grid Zones** (`/grid`): scores every ERCOT load zone on what a home battery could have
  earned there, and explains why. See [wiki/grid-economics.md](wiki/grid-economics.md).
- **Need** (`/need`): the **Need Engine**, described below. See [wiki/need-engine.md](wiki/need-engine.md)
  and, for the ML handoff, [wiki/ml-contract.md](wiki/ml-contract.md).

Stack: `apps/web` Next.js 16 + shadcn/ui + MapLibre · `apps/api` FastAPI + SQLAlchemy + Alembic
(Python 3.13, uv) · Postgres 17 + PostGIS · docker-compose. The [`wiki/`](wiki/README.md) is the
project knowledge base; start there before changing code.

---

## The big picture

A GTM decision needs three independent answers. We keep them separate on purpose: each one
is useful on its own, and a single blended number would hide *why* an area matters.

```text
   BASELINE NEED                PROPENSITY                    LIVE NEED
   "Would a battery be          "Who is likely to buy?"       "Why now?"
    structurally useful here?"
          │                          │                            │
   outage history,            permit history +            NWS alerts, forecasts,
   weather exposure           static Need features        ERCOT grid conditions
   (this repo)                (ML workstream)             (this repo)
          │                          │                            │
          └──────────────────────────┼────────────────────────────┘
                                     ▼
                              GTM OPPORTUNITY
                        "Who should Base target now?"
                     (the final combination, decided last)
```

| Need 95 / Propensity 20 | Need 35 / Propensity 95 | Need 90 / Propensity 90 + live event |
| --- | --- | --- |
| a battery would help a lot, but an unlikely buyer: educate | a likely buyer, weak product-need story | target now |

Everything joins on one geographic key: an **H3 cell**.

## How it works

```mermaid
flowchart LR
    subgraph sources["Public data (free, no keys)"]
        eaglei["ORNL EAGLE-I<br/>county outages, 15 min, 2014→"]
        eia["EIA-861<br/>utility reliability"]
        iem["NWS warnings<br/>(IEM archive)"]
        nclim["NOAA nClimGrid<br/>daily temperature"]
        nws["api.weather.gov<br/>alerts + forecast grid"]
        spc["SPC outlooks"]
        ercot["ERCOT dashboards<br/>+ public price reports"]
        census["Census counties"]
    end

    subgraph engine["Need Engine (apps/api)"]
        cells["H3 cells<br/>res 8 · Harris + Travis<br/>county · load zone"]
        outage["Outage Need<br/>county + utility"]
        weather["Weather Need<br/>storms (res 6) + temperature"]
        baseline["Baseline Need<br/>Texas percentile"]
        live["Live signals<br/>alerts · forecast · grid"]
        db[("Postgres + PostGIS<br/>features, scores, signals")]
        api["FastAPI<br/>/need/cells"]
    end

    subgraph ml["ML workstream"]
        feat["need_features.parquet"]
        model["Propensity model<br/>permit history + features"]
        pred["propensity.parquet"]
    end

    map["Map (apps/web)<br/>colour by Baseline Need,<br/>Propensity, Outage, Weather;<br/>click a cell → why"]

    census --> cells
    eaglei --> outage
    eia --> outage
    iem --> weather
    nclim --> weather
    outage --> baseline
    weather --> baseline
    nws --> live
    spc --> live
    ercot --> live
    cells --> db
    baseline --> db
    live --> db
    db --> api --> map
    db -- export-ml --> feat --> model --> pred -- import-propensity --> db
```

### 1. One geography for everything: H3 cells

External data comes in incompatible shapes (county polygons, utility territories, NWS alert
polygons, weather grids, permit addresses). Instead of joining each one to every other, we
normalise all of it onto **H3 resolution-8 hexagons** (~0.74 km²): the unit of computation
and the join key shared with the ML model.

```text
county / load zone / alert polygon / forecast grid / permit address
                          │
                          ▼   (PostGIS + the H3 library)
                     H3 res-8 cell  ──►  8,715 cells: Harris (Houston) + Travis (Austin)
                          │
            ┌─────────────┴─────────────┐
      Need features                Propensity
```

Each cell knows its **county** and **ERCOT load zone** (assigned by the cell's centre, with
the same rule the leads use, so a lead and its cell never disagree). Storm exposure is
computed on a coarser statewide **res-6 grid** (~36 km², 16,697 cells covering Texas) that
also serves as the reference population for every percentile.

### 2. Baseline Need: the structural case

Every score is a **Texas percentile** ("more than X% of Texas"), never a scale invented for
two counties. Raw numbers sit next to every percentile so a salesperson can quote them.

| Component | Sub-score | Measures | Source | Grain |
| --- | --- | --- | --- | --- |
| **Outage Need** | Observed Outage Exposure | outage hours per customer, 5 years | ORNL EAGLE-I | county |
| | Utility Reliability Need | SAIDI excluding major events, 5-year mean | EIA-861 | utility |
| **Weather Need** | Storm Exposure | days under severe-thunderstorm / tornado / extreme-wind warnings | NWS via IEM | res 6 |
| | Temperature Extremes | days ≥ 100 °F and ≤ 28 °F, measured | NOAA nClimGrid | county |

**Baseline Need** combines Observed Outage Exposure (O) and Weather Need (W) with a
union-style rule, then ranks the result against all 16,697 Texas res-6 cells:

```text
raw = 100 × (1 − (1 − O/100) × (1 − W/100))        "at least one strong structural reason"
Baseline Need = percentile of raw across Texas       plus the dominant driver: outage / weather / both
```

Three design decisions came from measuring, not guessing (details in the wiki):

- **Measured temperature, not NWS heat/cold advisories.** Across 254 Texas counties,
  advisory counts don't track measured extremes (rank correlation −0.29 for heat), and the
  issuing NWS office explains 85% of their variance. Storm *warnings* do track severe
  weather reports (0.76), so those are used.
- **Outage hours per customer, not "major event" counts.** Event counts fall as county
  size grows (one feeder fault is 5% of a small county), which put Harris at the 9th
  percentile. Hours per customer is size-normalised and cross-checks with EIA's SAIDI.
- **Union, not mean.** Outage and weather exposure are *complementary* across Texas
  (rank correlation −0.38: the coast is outage-heavy, the Panhandle weather-heavy). A mean
  would push those one-sided places to the middle.

### 3. Live signals: the "why now"

Live data is **observed and stored, but not yet scored**: the scoring rule will be decided
from real collected overlaps, not invented from a quiet afternoon. Two rules hold everywhere:

- **Official and derived are never shown as equivalent.** An NWS Tornado Warning or an
  ERCOT Energy Emergency Alert is official. "Wind gusts ≥ 58 mph forecast tomorrow" or
  "reserves below 3,000 MW" is *our* reading of NWS/ERCOT data, labelled as such (solid red
  vs dashed amber on the map).
- **Whether a signal is active is decided at read time**, with an explicit clock: an alert
  ending at 15:30 simply stops matching at 15:30. Nothing needs cleaning up, and every
  signal is kept for history.

| Signal | Kind | Source | Refresh |
| --- | --- | --- | --- |
| NWS Alerts (tornado, severe storm, tropical, winter, heat, cold) | official | api.weather.gov | 5 min |
| Forecast Signals (wind, heat index, cold, ice; SPC severe-storm outlook), next 48 h | derived | NWS forecast grid, SPC | hourly |
| ERCOT Grid Condition (Normal / Conservation / EEA 1–3) | official | ERCOT dashboard | 5 min |
| Grid Stress Signals (low reserves, tight margin, real-time / day-ahead price spikes) | derived | ERCOT dashboards + public price reports | 5–15 min |

Failures never erase good data: a failed fetch is logged, the last successful state stays,
and it is flagged **stale** after a set time.

### 4. The ML handoff

The Need Engine and the propensity model are decoupled by two boring files, both keyed by
`h3_index` and stamped with a `feature_version` ([wiki/ml-contract.md](wiki/ml-contract.md)):

```text
Need Engine ── need_features.parquet ──────────► Propensity model ── propensity.parquet ──► Need Engine
               (1 row per cell: geography,          (permit history +      (h3_index, score 0–100,
                raw history, scores, versions)       static features)       model_version, scored_at)
```

**The propensity model receives static, historical features only.** Live weather and grid
signals change hour to hour; they would let a model "explain" a 2023 permit with today's
heat forecast. They are combined downstream, later, with Baseline Need and Propensity into
GTM Opportunity.

## What it shows today

| | Houston (Harris) | Austin (Travis) |
| --- | --- | --- |
| Observed Outage Exposure | 76 (118 outage hours per customer in 5 years; Uri, the 2024 derecho and Beryl are all detected) | 52 |
| Storm Exposure | 20–76 across the county (NW Houston highest) | 22–48 |
| Temperature Extremes | 8 (dry-bulb only: humid heat is under-rated, see limitations) | 47 |
| Baseline Need | 36–59, driven by outage history | 21–30 |

The stormiest cells in Texas are around Amarillo; the highest outage exposure is on the Gulf
Coast. On a quiet day the live panel is empty by design; the worker keeps collecting.

## Honest limitations

- Temperature uses dry-bulb data, so Houston's humid heat is under-counted (the live
  forecast already uses heat index; the historical fix is backlog #21).
- Outage history is county-level: every cell in a county shares it. Satellite night-light
  detection (NASA Black Marble) is the planned route to within-county outage detail.
- Utility reliability is known only for CenterPoint and Austin Energy.
- Live signals are observed, not scored; there is no Live Need or Opportunity number yet.
- The reference population is area-weighted ("% of Texas land"), not customer-weighted.

## Data sources

Every external endpoint the code calls. All are public; only the optional ERCOT Public API
needs an account. Raw downloads are cached under `apps/api/data/` (gitignored).

### Need Engine (`/need`)

| Source | What we use it for | Endpoint | Access / licence | Refresh |
| --- | --- | --- | --- | --- |
| **ORNL EAGLE-I** | County customers-out every 15 min, 2021–2025 → Outage Events, outage hours per customer | `https://api.figshare.com/v2/articles/24237376` (file list; each file via its `download_url`, plus `MCC.csv` modeled customers) | none · CC BY 4.0 | manual (`outage download`); ~2 months after year end |
| **EIA Form 861** | Utility SAIDI/SAIFI (reliability) 2020–2024 | `https://www.eia.gov/electricity/data/eia861/zip/f861{year}.zip`, older years `…/eia861/archive/zip/f861{year}.zip` | none · public domain | manual; yearly |
| **NWS warnings (Iowa Environmental Mesonet archive)** | Severe thunderstorm / tornado / extreme wind warning polygons → Storm Exposure | `https://mesonet.agron.iastate.edu/cgi-bin/request/gis/watchwarn.py?accept=shapefile&states=TX&limit1=yes&sts=…&ets=…` | none · public domain (NWS) | manual (`weather download`) |
| **NOAA nClimGrid-daily (EpiNOAA)** | Daily county max/min temperature → days ≥ 100 °F / ≤ 28 °F | `https://noaa-nclimgrid-daily-pds.s3.amazonaws.com/EpiNOAA/v1-0-0/parquet/cty/YEAR={y}/STATUS={scaled\|prelim}/{yyyymm}.parquet` | none · public domain | manual; months of lag |
| **US Census cartographic boundaries** | County polygons (Harris, Travis; all Texas for the res-6 reference) | `https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_500k.zip` | none · public domain | once (committed / cached) |
| **NWS API: active alerts** | Live NWS Alerts for Texas | `https://api.weather.gov/alerts/active?area=TX` | User-Agent header required · public domain | every 5 min (worker) |
| **NWS API: forecast zones** | Areas of zone-based alerts | `https://api.weather.gov/zones/{forecast\|county}/{UGC}` (from each alert's `affectedZones`) | User-Agent · public domain | on first use, cached |
| **NWS API: points / gridpoints** | 48 h forecast (wind gust, heat index, temperature, ice) at 234 points | `https://api.weather.gov/points/{lat},{lng}` (once per point), `https://api.weather.gov/gridpoints/{office}/{x},{y}` | User-Agent · public domain | hourly (worker) |
| **NOAA Storm Prediction Center** | Day 1–2 severe-storm outlooks | `https://www.spc.noaa.gov/products/outlook/day1otlk_cat.lyr.geojson`, `…/day2otlk_cat.lyr.geojson` | none · public domain | hourly (worker) |
| **ERCOT dashboards** | Official grid condition (Normal / EEA), reserves (PRC), capacity vs demand forecast | `https://www.ercot.com/api/1/services/read/dashboards/daily-prc.json`, `…/supply-demand.json` | none · public | every 5 min (worker) |
| **ERCOT MIS reports (live prices)** | Real-time (NP6-905, report 12301) and day-ahead (NP4-190, report 12331) zone prices | list `https://www.ercot.com/misapp/servlets/IceDocListJsonWS?reportTypeId={id}`, file `https://www.ercot.com/misdownload/servlets/mirDownload?doclookupId={docId}` | none · public | 15 min / hourly (worker) |

### Grid Zones (`/grid`) and lead valuation

| Source | What we use it for | Endpoint | Access / licence |
| --- | --- | --- | --- |
| **ERCOT MIS yearly price files** | Historical real-time (report 13061) and day-ahead (13060) load-zone/hub prices | same MIS list/download endpoints as above | none · public |
| **ERCOT Public API** (optional) | Most recent days of prices | `https://api.ercot.com/api/public-reports/np6-905-cd/spp_node_zone_hub`, `…/np4-190-cd/dam_stlmnt_pnt_prices`; token from `https://ercotb2c.b2clogin.com/…` | ERCOT developer account (`.env`) |
| **ERCOT load zones (ArcGIS, ICF 2022)** | Houston / North / South / West zone polygons | `https://services3.arcgis.com/fwwoCWVtaahwlvxO/arcgis/rest/services/ERCOT_Load_Zones/FeatureServer/7/query` | public layer · boundaries approximate |
| **HIFLD Electric Retail Service Territories** | Austin Energy and CPS territory polygons (LZ_AEN, LZ_CPS) | `https://services3.arcgis.com/OYP7N6mAJJCyH6hd/arcgis/rest/services/Electric_Retail_Service_Territories_HIFLD/FeatureServer/0/query` | public query; layer metadata restricts use to Platts MSA holders, **check before commercial use** |

The zone polygons are built once (`scripts/build_zone_geojson.py`) into the committed
`apps/api/app/grid/ercot-zones.geojson`. The battery dispatch model adapts
[wattgap](https://github.com/saivarun3407/wattgap) (MIT, `app/grid/LICENSE-wattgap`).

### Leads (`/leads`)

| Source | What we use it for | Endpoint | Access / licence |
| --- | --- | --- | --- |
| **Harris Central Appraisal District (HCAD)** | Properties: owner, value, size, solar, pool | `https://download.hcad.org/data/CAMA/{year}/…` | public download · no explicit reuse licence |
| **HCAD parcels** | Parcel points (lead map location) | `https://download.hcad.org/data/GIS/Parcels.zip` | public download · no explicit reuse licence |
| **ERCOT TDSP ESI ID extract** (MIS report 203) | Electric meters (eligibility: served by a Base utility) | MIS list/download endpoints, `reportTypeId=203` | none · public |
| **Harris County issued permits (ArcGIS)** | Solar / EV / new-home permits | `https://www.gis.hctx.net/arcgishcpid/rest/services/Permits/IssuedPermits/FeatureServer/0` | public layer |
| **City of Houston sold permits** | Weekly permit reports | `https://www.houstonpermittingcenter.org/sold-permits-search` | public page · no explicit reuse licence |

Get Base legal sign-off before exporting lead data outside the team (see
[wiki/residential-leads.md](wiki/residential-leads.md)). Full research notes per lead source:
`apps/api/app/leads/sources.yaml`.

### Map

| Source | Use | Endpoint | Licence |
| --- | --- | --- | --- |
| **OpenFreeMap** | Basemap tiles | `https://tiles.openfreemap.org/styles/positron` | free, no key · OpenStreetMap data (ODbL, attribution shown on the map) |

### Evaluated and not used

- **CenterPoint / Oncor outage maps**: terms are personal / non-commercial; not scraped.
- **PowerOutage.us**: paid; free tier is non-commercial.
- **NWS heat/cold advisory counts**: measured to be mostly NWS-office practice, not climate (see the Need Engine section above).
- **PUCT Beryl/Derecho ZIP-level outage filings**: public record but no explicit licence; parked pending legal review.

## Where things live

| | |
| --- | --- |
| Geography | `apps/api/app/geo` (the H3 contract, no framework dependencies), `apps/api/app/need/markets.py` |
| Need Engine | `apps/api/app/need/` (`outage/`, `weather/`, `live/`, `baseline.py`, `ml.py`); CLI `python -m app.need` |
| API | `apps/api/app/routers/need.py`: `GET /need/cells?bbox=` (GeoJSON), `GET /need/cells/{h3}` (the full explanation) |
| Map | `apps/web/src/components/need/` |
| Decisions | [`CONTEXT.md`](CONTEXT.md) (the glossary every name follows), [`docs/adr/`](docs/adr/), GitHub issues #4–#23 (one spec per milestone) |

---

## Getting started

Prerequisites: Docker, Node 22+ with pnpm 10 (`corepack enable`), Python 3.13 + [uv](https://docs.astral.sh/uv/).

```bash
pnpm install
cp .env.example .env   # ERCOT API credentials (optional, see below)
pnpm up                # web http://localhost:3000 · api http://localhost:8000/docs
```

The database starts empty, so `/grid` shows nothing until you load prices. In another terminal:

```bash
docker compose exec api python -m app.grid backfill 2025 2026   # ~1 min, public ERCOT files, no login
docker compose exec api python -m app.grid compute              # score the zones
docker compose exec api python -m app.leads refresh             # lead sources (~10 min, ~1 GB download)
docker compose exec api python -m app.leads score               # score the leads
docker compose exec api python -m app.need seed                 # H3 Cells for /need (offline, seconds)
docker compose exec api python -m app.need outage download      # outage history, ~6 GB (cached)
docker compose exec api python -m app.need outage compute       # Outage Need on /need
docker compose exec api python -m app.need weather download     # NWS warnings + measured temperature
docker compose exec api python -m app.need weather compute      # Weather Need on /need
docker compose exec api python -m app.need baseline compute     # Baseline Need (default on /need)
docker compose exec api python -m app.need export-ml --out-dir data/ml   # features for the ML model
```

For the per-year battery value ranges shown on leads, also load past years (~1 min per year):
`docker compose exec api python -m app.grid backfill 2019 2020 2021 2022 2023 2024`, then `compute` again.

The `worker` service re-runs the grid and lead steps every Sunday at 03:00 Central, and keeps
the live Need signals fresh (NWS alerts and ERCOT conditions every 5 min, prices every 15 min,
forecasts hourly). The `app.need` history steps (outage, weather, baseline) are run by hand.

Then open http://localhost:3000 (redirects to `/leads`).

### ERCOT API credentials (optional)

The yearly files lag by up to a week. To pull the most recent days, register at
[developer.ercot.com](https://developer.ercot.com) and fill in `.env`: the subscription keys
**and** your ERCOT username and password (the API needs a login token, not just the keys).
Then:

```bash
docker compose exec api python -m app.grid update    # recent days via the ERCOT Public API
docker compose exec api python -m app.grid compute
```

Model assumptions (battery size, driver weights, lookback window) live in
`apps/api/app/grid/config.py`, not `.env`. Need Engine thresholds live in
`apps/api/app/need/config.py`. Re-run the relevant `compute` after changing them.

## Common commands

| What | Command |
| --- | --- |
| Start / stop everything | `pnpm up` / `pnpm down` |
| Apply migrations | `pnpm db:migrate` |
| New migration | `pnpm db:revision "describe change"` |
| API tests / lint | `cd apps/api && uv run pytest && uv run ruff check .` |
| Web lint / build | `pnpm lint:web` / `pnpm build:web` |

After adding a dependency, rebuild that container: `docker compose up -d --build --renew-anon-volumes web` (or `api`).

## Learn more

| Topic | Page |
| --- | --- |
| Running locally, host vs Docker, troubleshooting | [wiki/development.md](wiki/development.md) |
| How the zone scores are computed, data sources, caveats | [wiki/grid-economics.md](wiki/grid-economics.md) |
| Backend, database and migration rules | [wiki/backend.md](wiki/backend.md), [wiki/database.md](wiki/database.md) |
| Frontend structure and gotchas | [wiki/frontend.md](wiki/frontend.md) |
| Need Engine: H3 cells, Baseline Need, live signals, every source and threshold | [wiki/need-engine.md](wiki/need-engine.md) |
| Handing features to the ML propensity model, importing predictions | [wiki/ml-contract.md](wiki/ml-contract.md) |
| The glossary every name in the code follows | [CONTEXT.md](CONTEXT.md) |
