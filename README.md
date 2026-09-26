# base-power-gtm

Base Radar: turns public grid and property data into sales leads for Base.

- **Leads** (`/leads`, the home page): single-family, owner-occupied homes Base can serve
  (Harris County pilot), ranked by priority value, with the suggested battery size, talking
  points and a map. Refreshed weekly. See [wiki/residential-leads.md](wiki/residential-leads.md).
- **Grid Zones** (`/grid`): scores every ERCOT load zone on what a home battery could have
  earned there over the last 12 months, and explains why.
- **Need** (`/need`): the Need Engine. H3 cells over Harris and Travis counties scored on
  structural need for backup power (outage history + weather, **Baseline Need**), with live
  NWS alerts, forecast signals and ERCOT grid conditions, and the ML propensity handoff.
  See [wiki/need-engine.md](wiki/need-engine.md) and [wiki/ml-contract.md](wiki/ml-contract.md).

- `apps/web`: Next.js 16 + shadcn/ui + MapLibre (pnpm)
- `apps/api`: FastAPI + SQLAlchemy + Alembic (Python 3.13, uv)
- Postgres 17, everything wired with docker-compose
- [`wiki/`](wiki/README.md): project knowledge base. Start there before changing code.

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
`apps/api/app/grid/config.py`, not `.env`. Re-run `compute` after changing them.

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
| Need Engine: H3 cells, Baseline Need, live signals | [wiki/need-engine.md](wiki/need-engine.md) |
| Handing features to the ML propensity model, importing predictions | [wiki/ml-contract.md](wiki/ml-contract.md) |
