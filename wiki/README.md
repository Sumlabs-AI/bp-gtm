# Wiki

Knowledge base for AI agents (and humans) working in this repo. Read this index first, then open only the pages relevant to your task.

| Page | Read when |
| --- | --- |
| [architecture.md](architecture.md) | You need the big picture: services, how they talk, where code lives |
| [development.md](development.md) | Running, testing, linting, or debugging locally |
| [backend.md](backend.md) | Touching `apps/api` (FastAPI, SQLAlchemy, routes, schemas) |
| [database.md](database.md) | Changing models, writing migrations, or touching Postgres |
| [grid-economics.md](grid-economics.md) | Working on ERCOT price ingestion, zone scoring, or the grid UI |
| [residential-leads.md](residential-leads.md) | Working on lead sources/adapters, scoring, the weekly refresh, or the leads API |
| [need-engine.md](need-engine.md) | Working on H3 Cells, the Need Engine, `/need`, or the shared geo contract for ML |
| [ml-contract.md](ml-contract.md) | Handing Need features to the ML workstream, or importing Propensity predictions |
| [frontend.md](frontend.md) | Touching `apps/web` (Next.js, shadcn/ui, calling the API) |
| [conventions.md](conventions.md) | Before committing: style, naming, and rules of the road |

Ideas we're keeping for later (not scheduled) live in [`ideas/`](../ideas/README.md).

## Maintaining the wiki

- Keep pages short and factual. Prefer commands and file paths over prose.
- When you change how something works, update the relevant page in the same change.
- Add a new page only when a topic doesn't fit an existing one, and add it to the table above.
