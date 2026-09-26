# Residential leads

Finds single-family, owner-occupied homes Base can serve, scores them, and flags what's
new each week. Pilot: Harris County (CenterPoint). Lead = property, not a person: we keep
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
| `ercot_esiid` | ERCOT TDSP ESI ID extract (report 203), CenterPoint | `meters` |
| `harris_permits` | Harris County issued permits (ArcGIS) | `permits` |
| `houston_permits` | City of Houston weekly sold-permit XLSX | `permits` |

## Eligibility and score

A property becomes a lead only if it is single-family (state class A1), has a homestead exemption (owner-occupied), is not a confidential record (Tax Code 25.025), and its address matches an **active residential meter on a TDSP Base serves** (`BASE_TDSPS` in `app/leads/config.py`).

Drivers (0–100, weights in `app/leads/config.py`): home size and home value are percentiles among eligible homes; solar (appraisal record **or** permit), EV charger, pool/spa (a large, steady electric load), new owner (owner changed on the appraisal roll within the lookback) and new home (recent year built, new-home permit or new meter) are yes/no. Score = weighted average. `reasons` names the two strongest drivers.

## What counts as "new"

The first load of each source is the **baseline**: nothing in it is announced as new. After that, a lead's `trigger`/`triggered_at` is its latest event: new solar/EV/new-home permit, new electric meter, new owner, or newly eligible. A trigger is kept until a newer one replaces it, and the reviewer's `status` (new/reviewed/qualified/excluded) survives re-scoring. `GET /leads?new_only=true` = triggered in the last 7 days.

## Commands

```bash
docker compose exec api python -m app.leads refresh            # all sources (skips unchanged)
docker compose exec api python -m app.leads refresh hcad --force
docker compose exec api python -m app.leads score
docker compose exec api python -m app.worker --now             # the full weekly job, once
```

The `worker` compose service runs the weekly job every Sunday 03:00 Central: ERCOT prices → grid scores → lead sources → lead scores.

## API

`GET /leads/geo?bbox=w,s,e,n&zoom=` (same filters as the list) returns GeoJSON: lead points, or grid cells with `count` and average `score` when more than `MAX_MAP_POINTS` (5,000) leads are in view; the county-wide view takes <1 s. `GET /leads/summary`, `GET /leads` (filters: `min_score`, `signals` (repeatable), `new_only`, `zip`, `status`, `sort`, `limit`, `offset`), `GET /leads/{id}`, `PATCH /leads/{id}` (`{"status": …}`), `GET /sources` (last run per source, for the data-health page).

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
