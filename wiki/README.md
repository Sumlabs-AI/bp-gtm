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
| [propensity.md](propensity.md) | Working on the Propensity Score: the home-value rule, why it replaced the ML model, how to rebuild it |
| [research-process.md](research-process.md) | You want the story of the Propensity research: plan vs reality, the three data workstreams, discoveries, how we worked |
| [ml-contract.md](ml-contract.md) | Handing Need features to the ML workstream, or importing Propensity predictions |
| [eligibility.md](eligibility.md) | Working on the drawer's install-eligibility proof of concept |
| [frontend.md](frontend.md) | Touching `apps/web` (Next.js, shadcn/ui, calling the API) |
| [`ml/README.md`](../ml/README.md) | Working on ML data prep (permit labels, Jev extraction, block-group features) |
| [`ml/RESEARCH.md`](../ml/RESEARCH.md) | Why Propensity is a home-value rule and not a model: every experiment, result and open question ([ADR 0002](../docs/adr/0002-propensity-home-value-rule.md)) |
| [conventions.md](conventions.md) | Before committing: style, naming, and rules of the road |

Ideas we're keeping for later (not scheduled) live in [`ideas/`](../ideas/README.md).

## Maintaining the wiki

- Keep pages short and factual. Prefer commands and file paths over prose.
- When you change how something works, update the relevant page in the same change.
- Add a new page only when a topic doesn't fit an existing one, and add it to the table above.
