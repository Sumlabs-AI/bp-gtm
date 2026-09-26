# Conventions

## General

- Make the smallest change that solves the task. Don't refactor unrelated code.
- Match the style of surrounding code.
- Update the relevant `wiki/` page when behavior, commands, or structure change.
- Never commit secrets. `.env` / `.env.local` are git-ignored; document new variables in the matching `.env.example`.

## Python (`apps/api`)

- Formatting/linting: ruff (line length 100). Type-hint everything.
- SQLAlchemy 2.0 typed style (`Mapped`, `mapped_column`, `select()`).
- Pydantic v2 (`model_config = ConfigDict(...)`, `model_validate`, `model_dump`).
- Files and modules: `snake_case`. Tables: plural `snake_case` (`items`).

## TypeScript (`apps/web`)

- ESLint via `pnpm lint`. Strict TypeScript.
- Components: `PascalCase` exports; files `kebab-case.tsx` (shadcn convention).
- Server components by default; add `"use client"` only when you need state, effects, or browser APIs.

## Done means

- Lint, tests, and build pass for every app you touched (see [development.md](development.md)).
- Schema changes include a reviewed migration.
