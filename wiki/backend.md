# Backend (`apps/api`)

FastAPI + SQLAlchemy 2.0 (sync, typed `Mapped[...]` style) + Pydantic v2 + Alembic. Managed with uv.

## Layout

```
apps/api/
├── app/
│   ├── main.py        FastAPI app, CORS, router registration
│   ├── config.py      Settings (pydantic-settings; env vars / .env)
│   ├── db.py          Engine, SessionLocal, Base (with naming convention), get_db dependency
│   ├── models/        SQLAlchemy models — one file per model, re-exported in __init__.py
│   ├── schemas.py     Pydantic request/response models
│   └── routers/       One APIRouter per resource
├── alembic/           Migrations (see database.md)
├── tests/
└── pyproject.toml
```

## Adding a resource (checklist)

1. Model in `app/models/<name>.py`, subclassing `app.db.Base`.
2. Re-export it in `app/models/__init__.py` (**required** — Alembic only sees imported models).
3. Pydantic schemas in `app/schemas.py` (`<Name>Create`, `<Name>Read` with `from_attributes=True`). Split into `app/schemas/` once it grows.
4. Router in `app/routers/<name>.py`; register it in `app/main.py`.
5. Generate and review a migration (see [database.md](database.md)).
6. Add tests in `tests/`.

## Patterns

- Get a session with the `get_db` dependency: `db: Annotated[Session, Depends(get_db)]`.
- Query with SQLAlchemy 2.0 style: `db.scalars(select(Model).where(...))`, not the legacy `db.query(...)`.
- Commit explicitly in the route (or a service function) that owns the write.
- Use `response_model=` on routes so output is validated and documented.
- Configuration comes from `app.config.settings`; never read `os.environ` directly.
