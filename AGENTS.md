# AGENTS.md

Monorepo: Next.js + shadcn/ui frontend (`apps/web`, pnpm) and FastAPI + SQLAlchemy + Alembic backend (`apps/api`, uv), Postgres, docker-compose.

**Start with [`wiki/README.md`](wiki/README.md)** — it indexes the project knowledge base. Read the pages relevant to your task before making changes, and update them when you change how things work.

Quick reference:

- Run everything: `pnpm up` (docker compose). Web :3000, API :8000 (`/docs`), Postgres :5432.
- Schema changes go through Alembic only — see [`wiki/database.md`](wiki/database.md).
- `apps/web/AGENTS.md` has Next.js-specific rules (this Next.js version has breaking changes).
