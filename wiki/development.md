# Development

## Prerequisites

Node 22+, pnpm 10 (`corepack enable`), Python 3.13 + [uv](https://docs.astral.sh/uv/), Docker.

## Run everything in Docker

```bash
pnpm up          # docker compose up --build
pnpm down        # docker compose down
docker compose down -v   # also wipe the database volume
```

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
| API tests | `uv run pytest` |
| API lint / format | `uv run ruff check . --fix && uv run ruff format .` |
| Web lint | `pnpm lint` |
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
