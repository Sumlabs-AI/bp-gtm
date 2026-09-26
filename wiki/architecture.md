# Architecture

```
base-power-gtm/
├── apps/
│   ├── web/          Next.js (App Router) + Tailwind v4 + shadcn/ui — pnpm workspace package "web"
│   └── api/          FastAPI + SQLAlchemy 2.0 + Alembic — Python project managed by uv
├── wiki/             This knowledge base
├── docker-compose.yml
├── package.json      Root scripts (pnpm workspace root)
└── pnpm-workspace.yaml
```

## Services (docker-compose)

| Service | Port | Notes |
| --- | --- | --- |
| `db` | 5432 | Postgres 17. User/password/db = `app`/`app`/`app`. Data in the `pgdata` volume. |
| `api` | 8000 | Runs `alembic upgrade head`, then `fastapi dev` (hot reload, source bind-mounted). |
| `web` | 3000 | `next dev` (hot reload, source bind-mounted). |

## Request flow

- **Server components** in `web` call the API at `API_URL` (`http://api:8000` inside compose).
- **Browser code** calls the API at `NEXT_PUBLIC_API_URL` (`http://localhost:8000`).
- The API allows CORS from `CORS_ORIGINS` (defaults to `http://localhost:3000`).
- The API talks to Postgres via `DATABASE_URL` using the `psycopg` (v3) driver: `postgresql+psycopg://...`.

## Interactive API docs

- Swagger UI: http://localhost:8000/docs
- OpenAPI JSON: http://localhost:8000/openapi.json
