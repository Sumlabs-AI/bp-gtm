# Frontend (`apps/web`)

Next.js 16 (App Router, Turbopack) + React 19 + Tailwind CSS v4 + shadcn/ui. TypeScript, `src/` dir, `@/*` import alias.

> Next.js 16 has breaking changes versus older versions. Before using an unfamiliar API, check the bundled docs in `apps/web/node_modules/next/dist/docs/` (see `apps/web/AGENTS.md`).

## Layout

```
apps/web/src/
├── app/
│   ├── layout.tsx         Root: fonts, TooltipProvider, Toaster
│   ├── globals.css        Theme tokens (light/dark)
│   └── (dashboard)/       Route group — every page inside gets the app shell
│       ├── layout.tsx     SidebarProvider + AppSidebar + SiteHeader
│       ├── leads/         Leads list + map (home: "/" redirects here), [id] detail
│       ├── grid/          Grid Zones: page.tsx (map + ranking), [zone]/page.tsx (detail)
│       └── data/          Data sources (Operations)
│       (each has loading.tsx / error.tsx; leads/[id] also not-found.tsx)
│   └── maplibre/[file]/   Serves MapLibre's web worker from node_modules (see below)
├── components/
│   ├── grid/              zone-map (MapLibre), zone-charts (recharts), driver-bars
│   ├── ui/                shadcn/ui primitives — generated; edit sparingly
│   ├── leads/             leads-map, status-control, priority-help, lead-return-link
│   ├── app-sidebar.tsx    Navigation: Leads, Grid Zones; Operations → Data sources
│   ├── site-header.tsx    Route title / breadcrumb
│   └── route-error.tsx    Shared error state
├── hooks/use-mobile.ts
└── lib/
    ├── api.ts             apiFetch<T>() + API types
    ├── grid.ts            /grid API types, scoreColor(), formatDriverValue()
    └── utils.ts           cn() class-merging helper
```

## App shell ("Base Radar")

Sales-first: `/` redirects to `/leads` (`next.config.ts`). The sidebar has Leads and Grid Zones, plus Operations → Data sources. The shadcn `dashboard-01` sample content was removed. To add a page inside the shell, create `src/app/(dashboard)/<route>/page.tsx`, add a nav entry in `components/app-sidebar.tsx` and a title in `components/site-header.tsx`. Pages outside the shell (e.g. login) go directly under `src/app/`.

UX conventions for leads (agreed in a design review, 2026-09-26):
- The list opens on the **Unreviewed** queue (`status=new`); "All leads" is `status=all`.
- **Priority value** (= fit/100 × historical grid value of the suggested size) is always labelled as a *ranking metric* with its explanation; it is not revenue or customer savings.
- Battery values are "Historical grid value to Base", always shown in 25 / 40 / 50 kWh order with the **suggested size** highlighted.
- Grid value detail uses progressive disclosure (design review with Codex, 2026-09-26): the list, map preview and lead tiles show only the realistic average-year value, always labelled with its basis ("Average year 2019–2025", or "Last 12 months" when history isn't loaded). The lead page's collapsed "Past years and how this is estimated" holds the last 12 months, the lowest/highest full year, the perfect-hindsight ceiling, a year-by-year table (from `GET /grid/zones/{zone}`, optional) and the method. The zone page shows the 25/40/50 estimate vs ceiling and the value-by-year chart by default; panels built on the 39.2 kWh zone battery are labelled "reference battery". Don't present "% of ceiling" as operating performance.
- Signals: list shows only recorded ones as badges; detail shows Yes/No with "No = not found in available records". Talking points cite the evidence (permit month, appraisal record) and only say "confirm…" for undated appraisal-only flags.
- Detail links carry a `back` param so returning keeps filters, sort, page and view.

## Grid Zones (`/grid`)

Dollar-led comparison (design review with Codex, 2026-09-26). `/grid` ("Compare Load Zones") leads with a table of all 8 Load Zones sorted by **Grid Value · 40 kWh · average year** (then last 12 months, and leads per zone with a "View leads" link to `/leads?zone=…&status=all`, or "No leads yet"), with a map colored by the same $ metric on a zero-based scale. The relative **Zone Economics Score** (last 12 months), its drivers and weights sit in the collapsed "Price analysis · Last 12 months", never as the headline. A 4/100 score is a relative index, not "bad value". `/grid/[zone]` shows the lead count and link, the 25/40/50 table (average year, last 12 months, average-year ceiling), then Grid Value by calendar year, then collapsed "Price analysis" (score, drivers, reference-battery charts) and "How Grid Value is estimated". Collapsibles use `components/disclosure.tsx`, which the lead page uses too. Data comes from `GET /grid/zones[/{code}]` plus `GET /leads/summary` (`by_zone`) — see [grid-economics.md](grid-economics.md). Both pages call `await connection()` so they're never prerendered at build time. `/leads` accepts `zone=` end to end (list, map, pagination, back links) and shows a removable Load Zone chip.

- Map: `react-map-gl/maplibre` + OpenFreeMap `positron` basemap (no API key). Zone shapes come from the API (`GET /grid/zones.geojson`, file `apps/api/app/grid/ercot-zones.geojson`), colored client-side with a MapLibre `match` expression from `scoreColor()`.
- **MapLibre worker gotcha:** MapLibre resolves its worker file relative to its own bundle, which Turbopack doesn't emit (→ 404, blank map). `zone-map.tsx` calls `setWorkerUrl("/maplibre/maplibre-gl-worker.mjs")`, served by `app/maplibre/[file]/route.ts` straight from `node_modules`.

## Leads (`/leads`) and data sources (`/data`)

`/leads` lists Harris County residential leads with URL-based GET filters (plain `<form method="get">`, no client state) and 50-per-page pagination; `/leads/[id]` shows score drivers, evidence, property facts and a review-status control (`PATCH /leads/{id}` from the browser, then `router.refresh()`). `/data` shows the last refresh of each source from `GET /sources`. `/leads?view=map` (`components/leads/leads-map.tsx`) fetches `GET /leads/geo` for the visible bounds on every move (debounced) with the same filters: points colored by score, or count cells when more than 5,000 leads are in view; `/leads/[id]` shows the home on a small map. Gotcha: `<Layer>`s must be direct children of `<Source>` (or set `source=` explicitly): a Fragment breaks react-map-gl's source injection. Code: `src/app/(dashboard)/{leads,data}`, `src/components/leads/`, `src/lib/leads.ts`. Backend and scoring: [residential-leads.md](residential-leads.md).

## Calling the API

Use `apiFetch<T>(path, init?)` from `@/lib/api`. It picks `API_URL` on the server and `NEXT_PUBLIC_API_URL` in the browser.

- Prefer fetching in **server components**. For per-request data, call `await connection()` (from `next/server`) and wrap the component in `<Suspense>`.
- Keep TypeScript types in `lib/api.ts` in sync with the Pydantic `*Read` schemas in `apps/api/app/schemas.py`. Consider generating them from `/openapi.json` once the API grows.

## UI

- Add components with `pnpm dlx shadcn@latest add <name> -c apps/web` (run from repo root). Style: `base-nova`, icons: `lucide-react`.
- Use theme tokens (`bg-background`, `text-muted-foreground`, `text-destructive`, …) instead of raw colors so dark mode works.
- Merge classes with `cn()` from `@/lib/utils`.
