# Need Engine

Scores **how useful backup power is** in a place, per **Cell** (H3 resolution-8 hexagon, ~0.74 km²). It is separate from lead scoring and from the ML Propensity Score, which join onto the same Cells by `h3_index`. Terms: [`CONTEXT.md`](../CONTEXT.md). Why PostGIS: [ADR 0001](../docs/adr/0001-postgis.md).

Status: **Milestones 1–3A (Cells, Load Zone, Baseline Outage Need)**. Cells exist for Harris and Travis counties. Each Cell has its ERCOT Load Zone and its county, plus an **Outage Need Component**, drawn on `/need`. There's no combined Need Score yet (`needScore: null`, see M6). Static geography is closed: a new geography is added only when a Need signal needs it. County was added in M3A for exactly that reason.

## The Cell contract (shared with ML)

| | |
| --- | --- |
| Index | H3, resolution **8**, as a 15-char lowercase hex string (e.g. `8844689341fffff`). Never a bigint. |
| Point → Cell | `app.geo.latlng_to_cell(lat, lng)` |
| Cell → center / polygon | `app.geo.cell_to_center(cell)` → `(lat, lng)`; `app.geo.cell_to_polygon(cell)` → GeoJSON `[lng, lat]` |
| Shape → Cells | `app.geo.polygon_to_cells(geojson_geometry)` (Polygon or MultiPolygon) |
| Boundary rule | A Cell belongs to a shape when its **center** is inside it, so edge Cells can extend past a county line. Enrichments (Load Zone, and any later geography) use the same center rule. |

`app.geo` has no database or FastAPI imports, so it can be copied or imported anywhere. The Propensity workstream can map existing points with it: `permits.lat/lon` and `properties.lat/lon` (HCAD parcel points).

## Code

- `app/geo/`: the H3 functions above, plus committed county boundaries in `app/geo/counties/tx-<market>.geojson`.
- `app/need/markets.py`: **Markets**, the named areas we seed (Harris 48201, Travis 48453). Config only; Cells don't record their Market.
- `app/need/config.py`: `h3_resolution` (8) and `viewport_max_cells` (20,000).
- `app/need/store.py`: `seed_polygon(db, geometry)` (idempotent bulk insert that returns generated / inserted / existing / seconds), plus viewport and single-Cell queries.
- `app/models/need.py`: `cells` table (`h3_index` PK, `resolution`, `center_lat`, `center_lng`, `geometry` Polygon 4326 with a GIST index). No feature columns: features get their own tables when real signals arrive.
- `app/need/enrich.py`: `enrich_load_zones(db)` sets `cells.load_zone` and returns a report (processed / assigned / unknown / per zone / changed / seconds).
- `app/routers/need.py`: the API below.

## Load Zone

A Cell's `load_zone` comes from `app.grid.zones.zone_for_points`, the **same function Leads use**: its center inside the zone polygon, and where polygons overlap (Austin Energy and CPS inside LZ_SOUTH) the smallest one wins. Same rule, same code, so there's no second implementation to drift. A Lead and its Cell can still differ in two cases. Near a zone boundary the parcel point and the Cell center can fall on different sides. And a Lead whose Cell is unknown still gets a zone from its TDSP fallback. Tests cover the rule once (`tests/test_grid_zones.py`) and check that Cells use it (`tests/e2e/test_need_e2e.py`).

- `enrich` recomputes **every** Cell on each run and writes only the rows that changed, so it's idempotent and picks up a new zone file or rule. `seed` runs it automatically.
- `None` = the center is outside every polygon. Harris has 95 such Cells on its edges: the zone polygons are simplified (`scripts/build_zone_geojson.py`). There is no fallback, unlike Leads, which fall back to their TDSP.
- Approximation: there are no LZ_LCRA/LZ_RAYBN polygons, so Travis Cells outside Austin Energy are LZ_SOUTH even where the load settles in LZ_LCRA.

Current split: LZ_HOUSTON 5,455 · LZ_SOUTH 2,205 · LZ_AEN 960 · unknown 95 (0.14 s for 8,715 Cells).

## Baseline Outage Need (M3A, issue #8)

Two separate public signals, each a **Texas percentile** (Reference Population: all Texas counties / utilities with usable data, not just our Markets). Raw metrics are kept next to percentiles.

```text
Cell ─┬─ county ── EAGLE-I 5y ── Texas percentile ── Observed Outage Exposure ─┐
      └─ utility ─ EIA-861 5y ── Texas percentile ── Utility Reliability Need ──┴─ Outage Need Component
```

- **Observed Outage Exposure** (`app/need/outage/eaglei.py`, `events.py`). ORNL EAGLE-I (CC BY 4.0): 15-minute customers-out per county.
  - Outage Events: a county is in an event while ≥ 0.1% of its customers are out. Gaps under 1 h are merged, single-sample spikes are dropped, and samples above 100% of customers are dropped.
  - Major Outage Event: peak ≥ 5% of customers, or ≥ 1 customer-hour per customer.
  - Features are computed over 365 days and 5 years, ending at **Data Through** (the last EAGLE-I timestamp), not today.
  - **Score = Texas percentile of 5-year outage hours per customer, and nothing else.** That metric is size-normalized: it's a county-level SAIDI, and it cross-checks with EIA (below). Major-event counts are *not* scored. Across Texas they fall as county size grows (rank correlation −0.50 with customers): small counties log ~15 "major" events a year, because one feeder fault crosses 5% of 1,000 customers. So Major Outage Events, peak share out, last observed major outage and Data Through are **explanatory history for Baseline Need only**. "Why now" is reserved for Live Need signals.
  - Event duration is county-level ("someone in the county was out"), never one customer's outage.
- **Utility Reliability Need** (`app/need/outage/eia.py`). EIA-861 (public domain): Texas percentile of the 5-year mean SAIDI **without** major event days (normal-conditions reliability). If fewer years exist, the ones available are used (`years_used`). SAIDI/SAIFI with major events are kept as context, and the raw yearly values are stored in `utility_reliability.yearly`. Only final releases are used (early releases are `f861<year>er.zip`).
- **Outage Need Component** (`component.py`) = mean of the sub-scores that exist, each fallback with a note:
  - Utility unknown, or known but unranked: Observed Outage Exposure alone.
  - County outside the Reference Population: Utility Reliability Need alone.
  - Neither: null.

  **The equal weights are a placeholder, not a validated model.** Thresholds and the utility map live in `app/need/config.py`.
- **Cell → county / utility.** County comes from `cells.county_fips`, set by `enrich` from the Market county files using the same center rule. Utility comes from config, with no territory layer, because HIFLD territories are license-restricted:
  - `LZ_AEN` → Austin Energy (1015)
  - Harris → CenterPoint (8901)
  - anything else → unknown. That includes the 2,205 Travis Cells outside Austin Energy, which are really Pedernales, Oncor or Bluebonnet.
- **Storage:**
  - Raw downloads go in `data/raw/{eaglei,eia861}` (gitignored, about 6 GB).
  - Normalized Texas data goes in `data/derived/eaglei_tx.parquet` (DuckDB, UTC timestamps).
  - Postgres holds only `county_outage_features` (one row per Texas county) and `utility_reliability_features` (one row per Texas utility). Cells don't duplicate them.
- **Missing data is null, never 0.**
  - ORNL publishes coverage per state, not per county. So a county joins the Reference Population when EAGLE-I has rows for it in ≥ 80% of the window's years. Outside the population it keeps its raw metrics but gets no percentile.
  - A county with no rows at all has unknown metrics.
  - Percentiles use the midrank: ties share their average rank, and nulls aren't ranked.
- **"Days since"** is derived when read, from the persisted `last_observed_major_outage_on`, and always shown with Data Through: "Last observed major outage: 284 days ago · history through Dec 31, 2025". The system doesn't monitor outages live.
- Latency: EAGLE-I is updated about 2 months after year end; EIA-861 finals come yearly. The 2025 early release isn't used.
- Known quirk: the May 2024 Derecho shows as two back-to-back Harris events (2024-05-16 → 05-18 05:45, then 06:45 → 05-24). A data gap just over the 1-hour merge rule splits it. The rule is kept on purpose rather than tuned to one event, and it doesn't affect the score.

### Real-data results (EAGLE-I 2021–2025, data through 2025-12-31; EIA-861 2020–2024)

- Pipeline: 5 files, 6.3 GB CSV → 52 MB Texas Parquet (13.4M rows). `compute` takes ~5–9 s. 253 of 254 counties are in the Reference Population; 68 of 72 utilities are ranked.
- Validation: Harris majors include Uri (2021-02-15, peak 24.9%), the Derecho (2024-05-16, 27.5%) and Beryl (2024-07-08, 90.9%, 75 h/customer). Travis: Uri (42.7%) and the Feb 2023 ice storm (28.8%).
- Outage Events per year (major in brackets): Harris 2021 117 (2) · 2022 77 (0) · 2023 146 (0) · 2024 283 (5) · 2025 397 (2). Travis 2021 122 (4) · 2022 152 (0) · 2023 174 (1) · 2024 185 (0) · 2025 165 (1). `outage validate` prints all of this.
- Cross-check, minutes per customer with major events (EAGLE-I county vs EIA SAIDI):

  | Year | Harris | CenterPoint | Travis | Austin Energy |
  | --- | --- | --- | --- | --- |
  | 2021 | 705 | 2,366 | 1,800 | 1,922 |
  | 2022 | 101 | 232 | 125 | 85 |
  | 2023 | 204 | 354 | 1,325 | 3,265 |
  | 2024 | 5,779 | 4,316 | 116 | 92 |

  Same order of magnitude, and the peaks fall in the same storm years. Harris 2021 is low: EAGLE-I's Uri data for Harris is known to be incomplete.
- Scores:
  - Harris exposure 75.7 (118.5 outage h/customer over 5 years). Travis 51.6 (59.9 h).
  - CenterPoint 46.3 (SAIDI excl. major events 151 min/yr). Austin Energy 24.3 (69 min/yr).
  - Outage Need: Houston Cell 61.0, Austin Energy Cell 37.9, Travis outside Austin Energy 51.6 (utility unknown).

## Commands

```bash
docker compose exec api python -m app.need seed                  # every Market; safe to re-run
docker compose exec api python -m app.need seed --market travis
docker compose exec api python -m app.need enrich                 # recompute load zones (after a zone file change)
docker compose exec api python -m app.need export --out /app/data/cells.csv # h3_index,resolution,center_lat,center_lng
docker compose exec api python -m scripts.download_counties       # refresh county files (Census, network)
docker compose exec api python -m app.need outage download         # EAGLE-I (5 yearly files, ~6 GB) + EIA-861, cached
docker compose exec api python -m app.need outage compute          # Texas Parquet -> county/utility features
docker compose exec api python -m app.need outage validate         # Major Outage Events per Market + minutes/customer by year
```

Seeding reads only the committed county files, so it needs no network. To add a county, add a `Market`, run `download_counties`, commit the GeoJSON, then seed it.

Measured (M-series laptop, Docker): seeding Harris creates 5,550 Cells in 0.35 s and Travis 3,165 in 0.17 s; a re-run inserts 0.

## API

- `GET /need/cells?bbox=west,south,east,north` returns a GeoJSON FeatureCollection. Each feature has `id` = `h3`, `properties: {h3, needScore}`. It returns **400** `"Viewport contains too many H3 cells. Zoom in to continue."` above `viewport_max_cells`, and **422** for a malformed bbox. Whole-Harris view: 5,550 Cells, ~0.15 s, ~2.3 MB uncompressed.
- `GET /need/cells` features also carry `outageNeed` (the Outage Need Component or null).
- `GET /need/cells/{h3}` returns `{h3, resolution, center: {lat, lng}, loadZone, needScore, components}`. `components.outage` holds the score, `observedOutageExposure` (county, metrics, percentiles, source, dataThrough, lastObservedMajorOutageOn, daysSinceLastObservedMajorOutage), `utilityReliabilityNeed` (utility, SAIDI/SAIFI, years used, or null) and `notes`, or **404** for an unknown or invalid index.

## Map (`/need`)

`components/need/cell-map.tsx`. Cells are hidden and not fetched below zoom `H3_MAP_MIN_ZOOM` (9, in `lib/need.ts`). Above that zoom it refetches on `moveend` (300 ms debounce, aborting the previous request). Cells are shaded by `outageNeed` (the neutral tint where it's null). Hovering shows the index. Clicking opens a sheet with the Cell detail: Load Zone, plus the Outage Need breakdown with raw metrics, sources and the "history through" date. The Houston/Austin buttons fly to each Market.

## Switching an existing database to PostGIS

The `db` image changed from `postgres:17-alpine` to Debian `postgres:17` + PostGIS (`docker/db/Dockerfile`). A volume created by the old image should be moved by dump and restore, not reused. Reusing it risks collation mismatches between musl and glibc and corrupt text indexes. Don't wipe the volume and re-download either: lead sources are large and ERCOT rate-limits.

```bash
docker compose exec -T db pg_dump -U app -Fc app > app.dump   # BEFORE pulling this change (old image running)
docker compose down
docker volume rm bp-gtm_pgdata                              # name: docker volume ls
docker compose up -d --build db
docker compose exec -T db pg_restore -U app -d app --no-owner < app.dump
docker compose up -d                                        # api runs alembic upgrade head (adds postgis + cells)
docker compose exec api python -m app.need seed
```

## Caveats

- The response isn't compressed yet. A whole-county view is ~2.3 MB; add gzip or round coordinates if the map feels slow on real networks.
- Utility outage maps (CenterPoint/Oncor) are non-commercial: don't scrape them. PowerOutage.us is paid. The PUCT Beryl/Derecho ZIP tables are parked pending Base legal review.
- M3A is county- and utility-level: every Cell in a county shares its Observed Outage Exposure. M3B (NASA Black Marble nighttime lights, ~500 m) is the planned source of within-county variation, validated against EAGLE-I.
