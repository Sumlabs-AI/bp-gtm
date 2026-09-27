# Residential leads

Finds single-family, owner-occupied homes Base can serve, scores them, and flags what's
new each week. Markets: Harris County (Houston, CenterPoint) and Travis County (Austin, Austin
Energy). Lead = property, not a person: we keep
public-record owner/mailing data for later outreach but never expose it in the API.

## Pipeline

```text
adapters (one per source)        store.py loaders           scoring.py           API
fingerprint → fetch → parse  →   upsert + change tracking → eligibility + score → /leads, /sources
      (app/leads/adapters)        (properties, meters,        (leads table)
                                   permits)
```

- `app/leads/sources.yaml`: researched source registry (URLs, fields, terms, refresh strategy). Written by a research agent; check `verified` and `notes` before relying on an entry.
- `app/leads/frames.py`: the canonical columns every adapter must return. **Read this before writing an adapter.**
- `app/leads/adapters/<source>.py`: `SOURCE_ID`, `fingerprint()`, `fetch(raw_dir)`, `parse(paths)`. Pure parsing, tested with tiny anonymized fixtures in `tests/fixtures/leads/`.
- `app/leads/pipeline.py`: `run_source()` skips unchanged sources (same fingerprint as the last success), keeps raw files in `apps/api/data/raw/<source>/<timestamp>/` (gitignored; ERCOT files expire upstream after ~1 month), refuses loads that shrink a source by >40% (quality gate), and logs every attempt in `source_runs`.
- `app/leads/address.py`: joins sources on a normalized address key (`"1200 N OAK ST 77002"`): upper-case, suffix/direction abbreviations, unit designators dropped, ZIP5.

| Source id | Adapter | Feeds |
| --- | --- | --- |
| `hcad` | Harris Central Appraisal District CAMA ZIPs (incl. `extra_features.txt`: solar PV, pools) | `properties` |
| `hcad_parcels` | HCAD parcel geodatabase (`Parcels.zip`), point inside each parcel, joined by account | `properties.lat/lon` |
| `ercot_esiid` | ERCOT TDSP ESI ID extract (report 203), CenterPoint and Oncor | `meters` |
| `harris_permits` | Harris County issued permits (ArcGIS) | `permits` |
| `houston_permits` | City of Houston weekly sold-permit XLSX | `permits` |
| `tcad` | Travis County's public copy of TCAD parcels (ArcGIS), single-family (A1) rows only | `properties` |
| `tcad_parcels` | Same layer, parcel polygons → one point per account | `properties.lat/lon` |
| `austin_permits` | City of Austin issued construction permits (Socrata `3syk-w9eu`), keyword-filtered | `permits` |

## Eligibility and score

> **Ranking changed (M8):** the GTM page ranks leads by their Cell's Opportunity Score, then the home's estimated consumption (the API still offers `sort=need`); the Lead Score below is still computed and served (`score`, `drivers`, `reasons`) but no longer shown or used for ranking. See [need-engine.md](need-engine.md#leads-and-cells-m8-issue-27).

A property becomes a lead only if it is single-family (state class A1), has a homestead exemption (owner-occupied), is not a confidential record (Tax Code 25.025), and its address matches an **active residential meter on a TDSP Base serves** (`BASE_TDSPS` in `app/leads/config.py`).

**Austin (Travis).** Austin Energy is a municipal utility: its meters aren't in the ERCOT ESI ID extract, and Base serves its customers through a partnership. A home whose parcel point falls in Austin Energy's territory (load zone `LZ_AEN`, `PARTNER_UTILITY_ZONES`) is eligible without a meter match (`tdsp = austin_energy`, no ESI ID, so no "new meter" signal). Outside it, Travis homes need an active residential **Oncor** meter (Oncor zero-pads house numbers, so `address_key` drops leading zeros). Homes served by the co-ops (Pedernales, Bluebonnet) aren't in the ERCOT extract, so they are **not leads**. The "new meter" baseline is per TDSP, so a utility's first load isn't flagged as new. TCAD's public layer has no exemption codes: owner-occupied = the owner's mailing address contains the property's house number and street (as in `ml/parcels/normalize.py`). It also has no living area or pools, so those drivers are **left out** of Travis leads' fit (the other weights are rescaled; `unknown_drivers`), not scored 0. Solar and EV come from Austin permits only.

Drivers (0–100, weights in `app/leads/config.py`): home size and home value are percentiles among eligible homes of the same county; solar (appraisal record **or** permit), EV charger, pool/spa (a large, steady electric load), new owner (owner changed on the appraisal roll within the lookback) and new home (recent year built, new-home permit or new meter) are yes/no. Score = weighted average. `reasons` names the two strongest drivers.

## Value to Base and priority

Each lead also gets an **estimated annual grid value** (`app/leads/value.py`):

1. **Load zone:** the lead's parcel point inside the zone polygons (`app.grid.zones.zone_for_points`, smallest polygon wins; the same rule Need Engine Cells use), else its TDSP (`TDSP_ZONES`).
2. **Battery values:** per size (25 / 40 / 50 kWh) the zone's realistic `value` (day-ahead planner) in an **average full calendar year** (`first_year`–`last_year`, e.g. 2019–2025), its perfect-hindsight `ceiling` for that average year, the last 12 months (`recent`) and the worst/best full year (`low`/`high` with the year). The average year is used because Base sells multi-year (~3-year) contracts and single years swing 5×. Without full-year history (`backfill` of past years) `value`/`ceiling` fall back to the last 12 months and the year fields are null. From `python -m app.grid compute`; see [grid-economics.md](grid-economics.md#battery-backtest). Run grid `compute` before lead `score`.
3. **Recommended size:** by heated sqft (`battery_sizing` in `app/leads/config.py`: <2,500 → 25, <4,000 → 40, else 50); a pool bumps it one size up. `sizing_reason` says why.
4. **Priority value** (`expected_value` in the API) = fit score / 100 × realistic value of the recommended size. `GET /leads` sorts by the home's Cell by default (`sort=need`: Baseline Need, then consumption, then this value; see [need-engine.md](need-engine.md)); also `opportunity` (the Cell's Opportunity Score, then consumption; the GTM page's default), `priority`, `value`, `consumption`, `triggered_at`. The fit score isn't a calibrated conversion probability, so this is a ranking index in dollars, not a revenue forecast.

It's a screening estimate of energy-trading value (after losses, $0.02/kWh wear and a 20% backup reserve): no retail margin, fees or ancillary services yet. In the Harris pilot every lead is in LZ_HOUSTON, so the zone doesn't change the ranking yet; it will once other TDSPs' counties are added (40 kWh, average year 2019–2025: Houston $891, North $845, West $1,058, i.e. West ≈ +19%, North ≈ −5% vs Houston; over only the last 12 months to 2026-09-20 North looked +28% and West +59%, another reason not to rank on one year). Years swing a lot: a 40 kWh battery in Houston would have made $310 in 2025 and $1,741 in 2023, and the last 12 months ($233) are among the quietest, which is why leads are valued on the average year and show the range.

## Estimated consumption

Each lead gets a **property-based estimate of the home's electricity use** (`leads.consumption`, `leads.annual_kwh`; `app/leads/consumption.py`): annual kWh (median) with a P10–P90 range, 12 monthly values for a typical year, summer/winter peak kW for this home (its highest day, not a diversified class average) and P(electric heat). v1 uses no bill or meter data. It's display-only: it doesn't change the fit score, sizing or priority value.

- **Annual kWh and peaks:** weighted log-linear fits on NREL ResStock 2025.1 (AMY2018) simulations of Harris County single-family detached homes (3,922 samples), one set for electric-heat homes and one for the rest. Inputs, from HCAD: heated sqft, year built, stories (≥1.5 = two-story), bedrooms (clipped 1–5), pool. Missing inputs take typical values. The level is scaled to EIA RECS 2020 billed kWh for Texas hot-humid single-family homes (15,577 kWh vs ResStock's 17,851: factor 0.873). ERCOT's average COAST residential premise (15,934 kWh, 2019–2025) agrees.
- **Heating fuel** isn't on any per-home public record, the most useful variable we're missing. P(electric heat) = the Census ACS 2024 5-year share of electric-heated homes in the home's block group (B25040, files cached in `data/raw/census/` by `app/leads/census.py`), shifted in log-odds so the county average equals ResStock's owner-occupied single-family share (34.1%). ACS counts apartments, which in Houston are more often electric. The annual estimate mixes the two fits by that probability, so the range widens when the fuel is uncertain.
- **Monthly shape:** ERCOT backcasted load profiles for the COAST weather zone, averaged 2019–2025: RESHIWR (winter-peaking) for electric heat, RESLOWR for the rest, weighted by each fuel's share of expected use.
- **Accuracy (be honest in the UI):** out-of-fold within ResStock, R² ≈ 0.3 on log annual kWh, median error ≈ 20%, MAPE ≈ 31%; peaks are weaker (R² 0.06–0.24). Real homes will be worse: plan on ±30–40% per home, while area totals land within ~5–10%. v2/v3 (real meter data via Smart Meter Texas, a heating-fuel append) are in [ideas/home-consumption-from-meter-data.md](../ideas/home-consumption-from-meter-data.md).
- **Solar homes:** the estimate is the home's total consumption, not the grid import a meter shows.

Refit (e.g. for a new ResStock or RECS release) with `uv run python -m scripts.fit_consumption_model` from `apps/api`. It downloads ~450 MB once into `data/raw/consumption_model/`, prints fit quality and writes `app/leads/consumption_model.json` (committed). Then re-run `score`.

## What counts as "new"

The first load of each source is the **baseline**: nothing in it is announced as new. After that, a lead's `trigger`/`triggered_at` is its latest event: new solar/EV/new-home permit, new electric meter, new owner, or newly eligible. A trigger is kept until a newer one replaces it, and the reviewer's `status` (new/reviewed/qualified/excluded) survives re-scoring. `GET /leads?new_only=true` = triggered in the last 7 days.

## Commands

```bash
docker compose exec api python -m app.leads refresh            # all sources (skips unchanged)
docker compose exec api python -m app.leads refresh hcad --force
docker compose exec api python -m app.leads score
docker compose exec api python -m app.worker --now             # the full weekly job, once
```

The `worker` compose service runs the weekly job every Sunday 03:00 Central: ERCOT prices → grid scores → lead sources → lead scores. It also takes a Live Weather Snapshot (NWS alerts) every 5 minutes; see [need-engine.md](need-engine.md).

## API

`GET /leads/geo?bbox=w,s,e,n&zoom=` (same filters as the list) returns GeoJSON: lead points, or grid cells with `count` and average `score` when more than `MAX_MAP_POINTS` (5,000) leads are in view; the county-wide view takes <1 s. `GET /leads/summary` (includes `by_zone`: leads per load zone, all statuses), `GET /leads` (filters: `county` (`harris` or `travis`), `min_score`, `signals` (repeatable), `new_only`, `zip`, `status`, `zone` (load zone code, e.g. `LZ_HOUSTON`), `sort`, `limit`, `offset`; `/leads/summary` also takes `county`), `GET /leads/{id}`, `PATCH /leads/{id}` (`{"status": …}`), `GET /sources` (last run per source, for the data-health page).

## Tests

`tests/e2e/` runs the real pipeline, loaders, scoring and HTTP API against a migrated `app_test` database (created automatically; needs `docker compose up -d db`). `tests/conftest.py` forces `DATABASE_URL` to the test DB before the app is imported, and the e2e fixture refuses any database not ending in `_test` because it truncates tables.

## Harris pilot numbers (first load, 2026-09-26)

| | Count |
| --- | --- |
| HCAD accounts | 1,628,327 |
| Single-family homesteads (not confidential) | 812,736 |
| CenterPoint ESI IDs (all statuses/types) | 4,341,068 |
| **Eligible leads** (matched an active residential CenterPoint meter) | **772,437 (95.0%)** |
| Leads with solar (appraisal + permits) / pool / EV permit / new-home signal | 16,830 / 95,503 / 0 / 16,810 |
| Leads with map coordinates (HCAD parcels) | 772,240 (99.97%) |

- Most unmatched homes have no active residential CenterPoint meter on the same street at all (likely another utility or a differently written address). A ZIP-less fallback would add only ~0.2%.
- Solar comes mostly from HCAD's appraisal "extra features" (~22k Harris accounts with PV panels); permits add little (Harris County's layer has only 2 residential solar permits ever; Houston's weekly reports start Jan 2026). Appraisal flags lag real installs, see [`ideas/solar-detection-from-imagery.md`](../ideas/solar-detection-from-imagery.md). EV signals are ~nil. Most scores sit between 10 and 50.
- There is no public per-home electric service size (amps) or usage. Proxies we use: heated sqft, pools/spas. Real usage needs customer consent (Smart Meter Texas) or Base's own customer data.
- "New owner" needs a second weekly HCAD snapshot before it can fire.
- Loading the ERCOT extract peaks at ~3.9 GB RAM; give Docker enough memory for the worker.
- ERCOT's firewall returned 403 after a day of repeated full downloads; the weekly cadence is far lighter, and failed runs keep the last good data.

## Caveats

- Terms: HCAD and Houston permit data have no explicit reuse license; confidential owners must stay excluded. Get Base legal sign-off before exporting leads outside the team.
- Utility outage maps (CenterPoint/Oncor) are non-commercial: don't scrape them.
- Co-ops Base serves (CoServ, GVEC, Farmers) aren't in the ERCOT extract; they need another eligibility source.
- ResStock is listed as CC BY 4.0 on OpenEI, but its 2025 README says "provided for research purposes only". It's fine for this internal tool; get Base legal to confirm before showing estimates to customers.
