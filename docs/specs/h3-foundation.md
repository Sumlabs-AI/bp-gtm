# Milestone 1 — H3 Cell Foundation

Tracked in [#4](https://github.com/mamalovesyou/bp-gtm/issues/4) (`ready-for-agent`). The issue is the source of truth; this file is a mirror.

## Problem Statement

Base's GTM team needs to know where residential battery backup is needed and where it is likely to be adopted. Those two signals come from different workstreams (the Need Engine and the ML propensity model) and from datasets with incompatible geographies (counties, ZIPs, ERCOT Load Zones, utility territories, weather polygons, outage areas, property coordinates). Today nothing in the product can hold or display a common geographic unit, so neither signal can be computed, joined, or seen on a map.

## Solution

Introduce the **Cell** (H3 resolution-8 hexagon) as the canonical geographic unit. Seed Cells for the initial Markets (Harris and Travis counties) from real county geometry, persist them with spatial indexing, expose them through a small viewport-driven API as GeoJSON, and render them on a new Need map in the dashboard. Ship a pure, dependency-free geo module and a Cell export so the ML engineer can map permits onto the same `h3_index` keys independently.

No Need Score is computed yet; `needScore` is `null` everywhere. This milestone proves the pipeline end to end: county polygon → Cells → database → API → MapLibre.

## User Stories

1. As a GTM analyst, I want to open a Need map in the dashboard, so that I can see the geographic substrate the Need Engine will score.
2. As a GTM analyst, I want to zoom into Houston or Austin and see hexagonal Cells covering the county, so that I understand the granularity at which Need will be reported.
3. As a GTM analyst, I want Cells to appear only once I am zoomed in enough, so that the map stays responsive and does not flood with thousands of tiny shapes at state level.
4. As a GTM analyst, I want to hover a Cell and see its identifier, so that I can reference a specific location when discussing it with the team.
5. As a GTM analyst, I want to click a Cell and see its detail (identifier, resolution, center, Need Score placeholder), so that I can drill into a location and later see why it has its score.
6. As a GTM analyst, I want the map to keep working as I pan and zoom, fetching only the Cells in view, so that exploration feels smooth.
7. As a GTM analyst, I want a clear message when I try to view too large an area, so that I know to zoom in rather than assume the map is broken.
8. As an ML engineer, I want a Python module that converts a lat/lng to an `h3_index` at the documented resolution, so that I can map permits and properties onto the same Cells the Need Engine uses without touching the database or API.
9. As an ML engineer, I want that module to also give me a Cell's center and polygon and to convert a polygon into Cells, so that I can aggregate and sanity-check my features spatially.
10. As an ML engineer, I want an exported flat file of every seeded Cell (`h3_index`, resolution, center), so that I can join my propensity output offline and verify coverage.
11. As an ML engineer, I want a written contract stating the H3 resolution, index format, and boundary rules, so that our outputs join on `h3_index` without ambiguity.
12. As a developer, I want a single CLI command that seeds Cells for a named Market from committed county geometry, so that a fresh environment can be populated without network access to external GIS services.
13. As a developer, I want that seed command to be idempotent and to report generated / inserted / existing counts and duration, so that I can rerun it safely and measure it.
14. As a developer, I want seeding to accept arbitrary geometry rather than being hard-coded to Harris County, so that new Markets can be added by adding a polygon file.
15. As a developer, I want a script that downloads county boundaries from the Census by stable GEOID and writes them into the repository, so that adding a Texas county is a one-liner rather than a manual GIS task.
16. As a developer, I want the H3 resolution and the viewport cap defined in one configuration place, so that they can be benchmarked and tuned without hunting for magic numbers.
17. As a developer, I want the API routes to contain no H3 implementation details, so that the geo logic stays reusable and testable in isolation.
18. As a developer, I want the database to support spatial queries and indexes, so that later milestones (Load Zone mapping, outage areas, weather alerts) do not require rebuilding GIS logic in application code.
19. As a developer, I want the decision to adopt PostGIS recorded as an ADR, so that future readers understand why the database image changed.
20. As a developer, I want database-backed tests that skip cleanly when no test database is configured, so that the suite stays runnable everywhere while still exercising real spatial queries locally.
21. As a developer, I want the wiki to document the Need Engine's geography, commands, and ML handoff, so that new contributors can onboard without reading the conversation history.
22. As a product owner, I want the architecture to extend to more counties and eventually statewide without redesign, so that the hackathon proof of concept is not throwaway.
23. As a product owner, I want the Cell table to stay minimal (no speculative feature columns), so that the schema evolves with real signals rather than guesses.

## Implementation Decisions

### Glossary

All naming follows `CONTEXT.md`: **Cell**, **Market**, **Load Zone**, **Need Score**, **Need Signal**, **Propensity Score**. `grid` continues to mean the existing ERCOT economics package and is not used for Cell concepts. The residential leads work (**Lead**, **Lead Score**, **Grid Value**, **Expected Value**, **Lead Cluster**) is a separate, existing feature: Lead Score is not the Propensity Score and Expected Value is not Opportunity.

### Geographic scope and resolution

- Markets: Harris County (GEOID 48201) and Travis County (GEOID 48453). "Austin" means Travis County only for now; Williamson and Hays are deferred.
- H3 resolution 8. Held as a single configuration value in the Need package (code-level Pydantic config, same pattern as the grid economics config), not an environment variable. Each Cell row also persists its resolution so mixed resolutions are detectable.
- Markets are configuration only. The Cell table has no `market` column; county and other enrichments arrive in later milestones via centroid point-in-polygon.

### Boundary rule

Polygon-to-Cell coverage uses the H3 library's default: a Cell is included when its center falls inside the polygon. Edge Cells may extend outside the county boundary. This is documented as an accepted approximation, consistent with the centroid rule planned for later enrichment.

### Database

- Switch the Postgres image to the PostGIS-enabled PostgreSQL 17 image. A migration enables the `postgis` extension. The worker service shares the same database and needs no change.
- New `cells` table:
  - `h3_index` — string, 15 characters, primary key
  - `resolution` — small integer, not null
  - `center_lat`, `center_lng` — double precision, not null
  - `geometry` — `geometry(Polygon, 4326)`, not null, GIST index
- `h3_index` is stored and exchanged everywhere as its canonical hexadecimal string. No bigint form anywhere in the contract.
- Responsibility split: H3 library owns cell identity and polygon-to-cell coverage; PostGIS owns storage, spatial indexing, viewport filtering, and future point-in-polygon/intersection queries. Do not reimplement H3 coverage as PostGIS intersection queries.
- Bulk insert with conflict-ignore on `h3_index` gives idempotency. Counts for the seed report come from the insert result, not from a pre-query.
- Recorded as an ADR: PostGIS chosen over the in-process alternative already proven in the repo (geopandas spatial join, as used for Lead Load Zone assignment) because upcoming milestones repeatedly query persistent spatial relationships across counties, Load Zones, weather polygons, outage areas and utility territories, and the map needs GIST-indexed viewport queries. Existing lead tables keep their plain lat/lon columns; no migration of them.
- Image swap procedure (the database now holds large lead datasets that are expensive and rate-limited to re-download): dump the database with the old image, switch the image, recreate the volume, restore the dump. Do not recreate the volume and re-fetch sources; ERCOT has returned 403 after repeated full downloads. Document the procedure in the wiki and notify other developers, since their local volumes are affected too.

### Geo module (ML engineer contract)

A pure module with no database or web-framework imports, exposing:

- lat/lng → `h3_index` (at the configured or an explicit resolution)
- `h3_index` → center lat/lng
- `h3_index` → polygon (GeoJSON-style ring, lng/lat order)
- polygon or multipolygon (GeoJSON geometry) → set of `h3_index`

This module is the only place H3 library calls live. Routes and stores call it; they do not call the H3 library directly. "Dependency-free" means no database or web-framework imports; it may use `h3` and the `shapely` already present via geopandas.

New Python dependencies: `h3` and `geoalchemy2` only. Shapely, pyproj and geopandas are already installed.

### Need package

- Configuration: `h3_resolution = 8`, `viewport_max_cells = 20_000`.
- `Cell` SQLAlchemy model following existing conventions (typed mapped columns, registered in the models package for Alembic).
- Store functions: `seed_polygon(session, geometry, resolution) → SeedReport` (generated, inserted, existing, duration) and a viewport query using `ST_Intersects` against `ST_MakeEnvelope(west, south, east, north, 4326)`, plus single-cell lookup.
- CLI following the existing `python -m app.grid <command>` argparse convention but in its own package: `python -m app.need seed --market <name>` and `python -m app.need export --out <path>`. `seed` prints the summary block (market, GEOID, resolution, generated, inserted, existing, duration). `export` writes CSV with `h3_index, resolution, center_lat, center_lng`.
- Market registry maps a market name to its committed county GeoJSON file and GEOID.

### County geometry

- Downloader script (Census cartographic boundary files, selected by GEOID, not county name, read with the geopandas dependency already in the project) writes committed GeoJSON files, one per county, inside the geo package next to the code. The API's `data/` directory is gitignored (raw lead downloads), so committed geometry must not live there. Follows the existing pattern of the ERCOT zone GeoJSON, which is committed next to the grid package code.
- Seeding reads only the committed files. No runtime dependency on Census availability. No bounding-box shortcuts; real county geometry is used.

### API

Two routes only, under `/need`:

- `GET /need/cells?bbox=west,south,east,north`
  - Viewport parameter follows the existing lead map convention (`bbox` as a comma-separated string, 422 when malformed) rather than four separate parameters.
  - Returns a GeoJSON `FeatureCollection`. Each feature: `id` = `h3_index`, `geometry` = Polygon, `properties` = `{ "h3": <h3_index>, "needScore": null }`.
  - If the viewport would exceed `viewport_max_cells`, respond with a client error (400) and `{"detail": "Viewport contains too many H3 cells. Zoom in to continue."}`.
- `GET /need/cells/{h3_index}`
  - Returns `{ "h3", "resolution", "center": { "lat", "lng" }, "needScore": null, "components": {} }`.
  - Unknown or malformed `h3_index` returns 404.

Routes use the existing `get_db` dependency, `response_model` pattern, and explicit commit-in-route convention (reads only here). No admin/seed endpoint.

### Web

- New `/need` page in the dashboard shell, server component by default, with a client map component.
- Map reuses the existing MapLibre worker workaround, tile style, navigation control, and the `apiFetch` helper with `NEXT_PUBLIC_API_URL`.
- Constant `H3_MAP_MIN_ZOOM = 9` in the need library module. Below it the Cell layer is hidden and no request is made.
- At or above it: on `moveend`, debounced, read the current bounds, call `GET /need/cells`, and replace the GeoJSON source data. No fetch on `move`. Cancel the in-flight request when a new one starts, mirroring the existing leads map.
- Layers: subtle fill, outline, and a highlight layer for hovered/selected Cell, mirroring the existing zone map's fill/line/selected structure. Layers must be direct children of their source (no Fragment wrapper), per the documented react-map-gl gotcha.
- Hover shows a tooltip with the `h3_index`. Click opens a side sheet (shadcn Sheet) showing the detail endpoint payload.
- On the "too many cells" error, show the API's message in place of the layer rather than failing silently.
- Initial view centers on Houston at a zoom at or above the minimum so Cells are visible immediately; Austin reachable by panning or a small market switcher (Houston / Austin) that flies the map.
- Follow the Next.js 16 rules in the web package's agent instructions (read bundled Next docs before writing route or page code).

### Documentation

- `CONTEXT.md` already holds the glossary.
- ADR: PostGIS adoption.
- New wiki page for the Need Engine: Cell definition, resolution, index format, boundary rule, seed/export/download commands, API contract, ML handoff, and the image-swap note.
- Update wiki index, database page (PostGIS, extension migration, image swap procedure), development page (seed step in getting started), and frontend page (Need map).
- The Need Engine wiki page's ML handoff section points the ML engineer at existing inputs they can map onto Cells with the geo module: the permits table (lat/lon) and the properties table (parcel points).

## Testing Decisions

A good test exercises external behaviour through the highest available seam and asserts on outputs a consumer would see (HTTP body, returned report, function result), not on internal calls or query shapes.

Three seams:

1. **HTTP** — FastAPI `TestClient` against a real PostGIS test database (prior art: the existing OpenAPI smoke test). Tests:
   - viewport query returns only Cells intersecting the bounds (seed a small known polygon; query inside, outside, and partially overlapping boxes)
   - response is valid GeoJSON (`FeatureCollection`, feature `id` equals `properties.h3`, Polygon rings closed, lng/lat order, `needScore` is null)
   - viewport exceeding the cap returns 400 with the documented message
   - detail returns the documented shape; unknown index returns 404
2. **Seed service** — call `seed_polygon` twice on a small polygon; first report inserted = generated, existing = 0; second report inserted = 0, existing = generated; row count unchanged.
3. **Pure geo module** — no database (prior art: the existing pure pandas metrics tests). Tests:
   - a known Houston lat/lng maps to a resolution-8 index of the expected form and round-trips to a center within the Cell
   - `h3_index` → polygon yields a closed ring of 7 points (6 unique) in lng/lat order
   - a small polygon yields a non-empty set of Cells all of whose centers lie inside or near the polygon; a multipolygon input is accepted

Database tests live alongside the existing end-to-end suite and reuse its harness: the test session is forced onto the `_test` database, which is created and migrated with Alembic automatically, and all tables are truncated between tests. Like the existing suite, they require Postgres running (now the PostGIS image) and abort rather than skip without it. Prior art: the grid and leads end-to-end tests. The CLI wrapper and the Census download script are not unit-tested (same treatment as the existing grid CLI and zone GeoJSON script).

Performance is measured, not asserted: the seed command's reported duration for Harris and Travis, and the response time and payload size of a full-county viewport request, go into the milestone report.

## Out of Scope

- Any Need Score, component score, or feature computation (Milestones 3–6).
- Static enrichment (county, ZIP, utility, Load Zone, Weather Zone) on Cells (Milestone 2).
- Outage, weather, or additional ERCOT integrations.
- Propensity model or Opportunity formula (ML workstream / Milestone 7). Permit ingestion already exists in the leads pipeline and is not changed.
- Any change to Leads, Lead Score, Expected Value, or the lead tables (no `h3_index` on properties or permits in this milestone).
- Multi-resolution H3, percentage-overlap boundary models.
- Admin/seed HTTP endpoints, bulk lat/lng lookup endpoints.
- Williamson, Hays, or other counties beyond Harris and Travis (supported by the mechanism, not seeded).
- Renaming existing `grid` / zone economics code for glossary compliance.
- Layer toggles (Need / Propensity / Opportunity / Outages / Weather / Grid) on the map.
- Redis, Kafka, data warehouse, microservices, or any additional datastore.
- Web test framework setup.

## Further Notes

- Expected scale: Harris ≈ 6.5k Cells, Travis ≈ 3.7k at resolution 8. Both fit comfortably under the 20k cap in a single county-wide viewport, which is why the cap and zoom gate are safety nets rather than active constraints today.
- The Cell export and the geo module are the deliverables to hand the ML engineer; the wiki page is the written contract. Confirm with them whether they work in this repository (import the module directly) or separately (use the export plus documented resolution).
- Known tension to revisit in Milestone 7: the product will have two rankings, Expected Value (per Lead, economics) and Opportunity (per Cell, Need × Propensity dimensions). Keep them distinct until the team decides how they relate.
- Milestone 3 constraint: utility outage maps (CenterPoint, Oncor) are non-commercial and must not be scraped. Historical outage data needs another source; research this before starting Milestone 3.
- Milestone 2 consistency: when assigning Cells to Load Zones, reuse the existing Lead rule (point inside zone polygon, smallest polygon wins) so a Lead and its Cell never disagree on Load Zone.
- After this milestone, stop and report: what was implemented, measured seed and query timings, tests added, and issues discovered (notably the database image swap) before starting the first real Need signal.
