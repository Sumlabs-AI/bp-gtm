# Wiki

Knowledge base for AI agents (and humans) working in this repo. Read this index first, then open only the pages relevant to your task.

| Page | Read when |
| --- | --- |
| [architecture.md](architecture.md) | You need the big picture: services, how they talk, where code lives |
| [development.md](development.md) | Running, testing, linting, or debugging locally |
| [backend.md](backend.md) | Touching `apps/api` (FastAPI, SQLAlchemy, routes, schemas) |
| [database.md](database.md) | Changing models, writing migrations, or touching Postgres |
| [grid-economics.md](grid-economics.md) | Working on ERCOT price ingestion, zone scoring, or the grid UI |
| [frontend.md](frontend.md) | Touching `apps/web` (Next.js, shadcn/ui, calling the API) |
| [conventions.md](conventions.md) | Before committing: style, naming, and rules of the road |

## Maintaining the wiki

- Keep pages short and factual. Prefer commands and file paths over prose.
- When you change how something works, update the relevant page in the same change.
- Add a new page only when a topic doesn't fit an existing one, and add it to the table above.
