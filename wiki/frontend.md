# Frontend (`apps/web`)

Next.js 16 (App Router, Turbopack) + React 19 + Tailwind CSS v4 + shadcn/ui. TypeScript, `src/` dir, `@/*` import alias.

> Next.js 16 has breaking changes versus older versions. Before using an unfamiliar API, check the bundled docs in `apps/web/node_modules/next/dist/docs/` (see `apps/web/AGENTS.md`).

## Layout

```
apps/web/src/
├── app/
│   ├── layout.tsx         Root: fonts, TooltipProvider, Toaster
│   ├── globals.css        Theme tokens (light/dark)
│   └── (dashboard)/       Route group — every page inside gets the dashboard shell
│       ├── layout.tsx     SidebarProvider + AppSidebar + SiteHeader
│       ├── page.tsx       Sample dashboard (unreachable: "/" redirects to /grid in next.config.ts)
│       ├── data.json      Placeholder table data for the sample dashboard
│       └── grid/          Grid Zones: page.tsx (map + ranking), [zone]/page.tsx (detail)
│   └── maplibre/[file]/   Serves MapLibre's web worker from node_modules (see below)
├── components/
│   ├── grid/              zone-map (MapLibre), zone-charts (recharts), driver-bars
│   ├── ui/                shadcn/ui primitives — generated; edit sparingly
│   ├── app-sidebar.tsx    Sidebar nav items (edit `data` to change navigation)
│   ├── site-header.tsx    Top bar
│   └── …                  Dashboard pieces from the shadcn `dashboard-01` block
├── hooks/use-mobile.ts
└── lib/
    ├── api.ts             apiFetch<T>() + API types
    ├── grid.ts            /grid API types, scoreColor(), formatDriverValue()
    └── utils.ts           cn() class-merging helper
```

## Dashboard shell

Based on the shadcn [`dashboard-01`](https://ui.shadcn.com/blocks#dashboard-01) block. To add a page inside the shell, create `src/app/(dashboard)/<route>/page.tsx` and add a nav entry in `components/app-sidebar.tsx`. Pages outside the shell (e.g. login) go directly under `src/app/`.

The sample dashboard page still shows **static placeholder data** from the block. `/` currently redirects to `/grid` (temporary redirect in `next.config.ts`).

## Grid Zones (`/grid`)

Map + ranked list of ERCOT load zones by Grid Value Score; `/grid/[zone]` explains one zone's drivers with charts. Data comes from `GET /grid/zones[/{code}]` — see [grid-economics.md](grid-economics.md). Both pages call `await connection()` so they're never prerendered at build time.

- Map: `react-map-gl/maplibre` + OpenFreeMap `positron` basemap (no API key). Zone shapes come from the API (`GET /grid/zones.geojson`, file `apps/api/app/grid/ercot-zones.geojson`), colored client-side with a MapLibre `match` expression from `scoreColor()`.
- **MapLibre worker gotcha:** MapLibre resolves its worker file relative to its own bundle, which Turbopack doesn't emit (→ 404, blank map). `zone-map.tsx` calls `setWorkerUrl("/maplibre/maplibre-gl-worker.mjs")`, served by `app/maplibre/[file]/route.ts` straight from `node_modules`.

## Leads (`/leads`) and data sources (`/data`)

`/leads` lists Harris County residential leads with URL-based GET filters (plain `<form method="get">`, no client state) and 50-per-page pagination; `/leads/[id]` shows score drivers, evidence, property facts and a review-status control (`PATCH /leads/{id}` from the browser, then `router.refresh()`). `/data` shows the last refresh of each source from `GET /sources`. `/leads?view=map` (`components/leads/leads-map.tsx`) fetches `GET /leads/geo` for the visible bounds on every move (debounced) with the same filters: points colored by score, or count cells when more than 5,000 leads are in view; `/leads/[id]` shows the home on a small map. Gotcha: `<Layer>`s must be direct children of `<Source>` (or set `source=` explicitly): a Fragment breaks react-map-gl's source injection. Code: `src/app/(dashboard)/{leads,data}`, `src/components/leads/`, `src/lib/leads.ts`. Backend and scoring: [residential-leads.md](residential-leads.md).

## Need (`/need`)

The H3 Cell map for the Need Engine: `components/need/cell-map.tsx`, types and `H3_MAP_MIN_ZOOM` in `lib/need.ts`. It is a static page, and the client component fetches `GET /need/cells?bbox=` on `moveend` above the minimum zoom. Details: [need-engine.md](need-engine.md).

## Calling the API

Use `apiFetch<T>(path, init?)` from `@/lib/api`. It picks `API_URL` on the server and `NEXT_PUBLIC_API_URL` in the browser.

- Prefer fetching in **server components**. For per-request data, call `await connection()` (from `next/server`) and wrap the component in `<Suspense>`.
- Keep TypeScript types in `lib/api.ts` in sync with the Pydantic `*Read` schemas in `apps/api/app/schemas.py`. Consider generating them from `/openapi.json` once the API grows.

## UI

- Add components with `pnpm dlx shadcn@latest add <name> -c apps/web` (run from repo root). Style: `base-nova`, icons: `lucide-react`.
- Use theme tokens (`bg-background`, `text-muted-foreground`, `text-destructive`, …) instead of raw colors so dark mode works.
- Merge classes with `cn()` from `@/lib/utils`.
