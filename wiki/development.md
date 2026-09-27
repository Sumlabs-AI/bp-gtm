# Development

## Prerequisites

Node 22+, pnpm 10 (`corepack enable`), Python 3.13 + [uv](https://docs.astral.sh/uv/), Docker.

## Run everything in Docker

The `db` image is Postgres 17 **+ PostGIS**, built from `docker/db/Dockerfile`. A volume created by the old `postgres:17-alpine` image must be moved by dump and restore before it works with it: see [need-engine.md](need-engine.md#switching-an-existing-database-to-postgis).

```bash
pnpm up          # docker compose up --build
pnpm down        # docker compose down
docker compose down -v   # also wipe the database volume
```

## Data snapshot (real scores out of the box)

The product only reads Postgres. The computed data it shows (Cells with Baseline Need and Propensity, Houston + Austin leads and their homes, grid values) is committed in `apps/api/snapshot/` (~100 MB of gzipped CSV, every file far under GitHub's 100 MB limit). On `pnpm up`, the api container loads it **when the database has no leads yet** (`python -m app.snapshot load`, ~35 s), so a fresh clone needs nothing else:

```bash
git clone … && cd bp-gtm && pnpm up    # http://localhost:3000/gtm
```

- Not in it: owner names and mailing addresses (so the CSV export's owner and mailing columns are empty on snapshot data: run the lead pipelines for a real mailing list); the ERCOT meters and raw grid prices (inputs to re-scoring); live data (NWS alerts, forecasts, ERCOT condition), which the worker fetches once running.
- It records its Alembic revision; after a migration, the load is skipped until the snapshot is re-exported.
- Replace existing data with it: `docker compose exec api python -m app.snapshot load --force`.
- Refresh it after re-running the pipelines: `pnpm snapshot:export`, then commit `apps/api/snapshot/`. Every export adds ~100 MB to git history: refresh rarely.

Everything below rebuilds the same data from the public sources instead (hours, ~15 GB of downloads).

## Load grid data

A fresh database has no prices, so `/grid` is empty. Load and score them (details in [grid-economics.md](grid-economics.md)):

```bash
docker compose exec api python -m app.grid backfill 2025 2026   # or: cd apps/api && uv run python -m app.grid …
docker compose exec api python -m app.grid compute
```

Seed the Need Engine Cells for `/need` (offline, a few seconds; see [need-engine.md](need-engine.md)):

```bash
docker compose exec api python -m app.need seed
docker compose exec api python -m app.need outage download   # optional: ~6 GB, cached in apps/api/data/raw
docker compose exec api python -m app.need outage compute    # Outage Need colours on /need
docker compose exec api python -m app.need weather download  # optional: ~60 MB warnings + temperature
docker compose exec api python -m app.need weather compute   # Weather Need colours on /need
docker compose exec api python -m app.need baseline compute  # Baseline Need
cd apps/api && uv run python -m app.need import-propensity ../../ml/output/propensity.parquet && cd -  # Propensity -> Opportunity Score (default colour on /need)
docker compose exec api python -m app.need live refresh      # live NWS alerts now (the worker repeats every 5 min)
docker compose exec api python -m app.need live forecast     # 48 h forecast signals (the worker repeats hourly)
```

ERCOT credentials go in the repo-root `.env` (see `.env.example`); only `update` needs them.

## Run apps on the host (faster iteration)

```bash
docker compose up -d db                  # just Postgres

cd apps/api
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run fastapi dev app/main.py           # http://localhost:8000

cd apps/web
cp .env.example .env.local
pnpm install                             # run from repo root the first time
pnpm dev                                 # http://localhost:3000
```

## Checks

| What | Command (from the app dir) |
| --- | --- |
| API tests (unit + e2e; e2e needs `docker compose up -d db`) | `uv run pytest` |
| API lint / format | `uv run ruff check . --fix && uv run ruff format .` |
| Web lint | `pnpm lint` |
| Web tests (`node --test`, no framework) | `pnpm test` |
| Web type-check + build | `pnpm build` |

Run the checks for every app you touched before declaring a task done.

## Dependencies

- Python: `uv add <pkg>` / `uv add --dev <pkg>` in `apps/api`. Commit `uv.lock`. Rebuild the api image afterwards (`docker compose build api`).
- JS: `pnpm --filter web add <pkg>` from the root. Commit `pnpm-lock.yaml`. Rebuild the web image afterwards.
- shadcn components: `pnpm dlx shadcn@latest add <component> -c apps/web` from the root.

## Troubleshooting

- **Web can't reach API in Docker**: server code must use `API_URL` (`http://api:8000`), not `localhost`.
- **New dependency missing in container**: rebuild the image; `node_modules` and the Python venv live in the image, not the bind mount.
- **Migration drift**: `uv run alembic check` reports whether models and migrations disagree.
