# Need Engine

Scores **how useful backup power is** in a place, per **Cell** (H3 resolution-8 hexagon, ~0.74 km²). It is separate from lead scoring and from the ML Propensity Score, which join onto the same Cells by `h3_index`. Terms: [`CONTEXT.md`](../CONTEXT.md). Why PostGIS: [ADR 0001](../docs/adr/0001-postgis.md).

Status: **Milestones 1–2 (Cells + Load Zone)**. Cells exist for Harris and Travis counties, each with its ERCOT Load Zone, and are drawn on `/need`. No Need Score yet (`needScore: null`). This closes the static-geography work: further geographies (county, ZIP, utility) are added only when a Need signal needs them.

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

## Commands

```bash
docker compose exec api python -m app.need seed                  # every Market; safe to re-run
docker compose exec api python -m app.need seed --market travis
docker compose exec api python -m app.need enrich                 # recompute load zones (after a zone file change)
docker compose exec api python -m app.need export --out /app/data/cells.csv # h3_index,resolution,center_lat,center_lng
docker compose exec api python -m scripts.download_counties       # refresh county files (Census, network)
```

Seeding reads only the committed county files, so it needs no network. To add a county, add a `Market`, run `download_counties`, commit the GeoJSON, then seed it.

Measured (M-series laptop, Docker): seeding Harris creates 5,550 Cells in 0.35 s and Travis 3,165 in 0.17 s; a re-run inserts 0.

## API

- `GET /need/cells?bbox=west,south,east,north` returns a GeoJSON FeatureCollection. Each feature has `id` = `h3`, `properties: {h3, needScore}`. It returns **400** `"Viewport contains too many H3 cells. Zoom in to continue."` above `viewport_max_cells`, and **422** for a malformed bbox. Whole-Harris view: 5,550 Cells, ~0.15 s, ~2.3 MB uncompressed.
- `GET /need/cells/{h3}` returns `{h3, resolution, center: {lat, lng}, loadZone, needScore, components}`, or **404** for an unknown or invalid index.

## Map (`/need`)

`components/need/cell-map.tsx`. Cells are hidden and not fetched below zoom `H3_MAP_MIN_ZOOM` (9, in `lib/need.ts`). Above that zoom it refetches on `moveend` (300 ms debounce, aborting the previous request). Hovering shows the index; clicking opens a sheet with the Cell detail (including its Load Zone). The Houston/Austin buttons fly to each Market.

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
- Utility outage maps (CenterPoint/Oncor) are non-commercial, so don't scrape them. Historical outage data (Milestone 3) needs another source.
