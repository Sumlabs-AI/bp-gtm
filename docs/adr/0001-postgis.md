# 1. PostGIS for Need Engine geography

Date: 2026-09-26 · Status: accepted

## Context

The Need Engine computes Need per **Cell** (H3 resolution 8). Every upcoming signal arrives in a different geography — county, ERCOT Load Zone, utility territory, NWS alert polygon, outage area, property point — and has to be mapped onto Cells, repeatedly, as data refreshes. The map also needs fast viewport queries over Cells.

The repo already proved an in-process alternative: Lead Load Zone assignment uses a geopandas spatial join against a committed GeoJSON file, and lead tables store plain `lat`/`lon` columns.

## Decision

Use PostGIS on PostgreSQL 17. The `cells` table stores each Cell's polygon as `geometry(Polygon, 4326)` with a GIST index.

Split of responsibilities:

- **H3 library** (`app.geo`): Cell identity and polygon → Cell coverage.
- **PostGIS**: storing boundaries, spatial indexes, viewport filtering, and future point-in-polygon / intersection queries.

Don't reimplement H3 coverage as PostGIS intersection queries.

The `postgis/postgis` image has no arm64 build, so the `db` service builds a small image: official `postgres:17` plus the Debian `postgresql-17-postgis-3` package (`docker/db/Dockerfile`).

## Alternatives

Plain Postgres with lat/lng columns, with spatial work done in Python (h3 + shapely/geopandas). This is simpler and already used for leads, but every spatial relationship would be recomputed in application code with no index. The viewport would be a lat/lng range scan that misses Cells whose center is outside the box.

## Consequences

- One more piece of database infrastructure: the image changed from Alpine to Debian.
- **Existing volumes:** switching from the Alpine image to the Debian one changes the C library. To keep data, dump the database before switching, recreate the volume, and restore (see `wiki/need-engine.md`). Don't recreate the volume and re-download sources: ERCOT has returned 403 after repeated full downloads.
- Lead tables keep their plain `lat`/`lon` columns; nothing forces them onto PostGIS.
- When Milestone 2 maps Cells to Load Zones, reuse the Lead rule (point inside the zone polygon, smallest polygon wins) so Leads and Cells share one rule (done in Milestone 2: `app.grid.zones.zone_for_points`, used by both).
