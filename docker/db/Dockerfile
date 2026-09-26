# Official Postgres 17 + PostGIS from the Debian packages. The postgis/postgis image
# has no arm64 build, so Apple Silicon machines can't run it.
FROM postgres:17
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-17-postgis-3 \
    && rm -rf /var/lib/apt/lists/*
