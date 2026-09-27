"use client"

import * as React from "react"
import { ArrowUpDownIcon, MapPinIcon, XIcon } from "lucide-react"

import { ExportMenu } from "@/components/gtm/export-buttons"
import { LeadDrawer } from "@/components/gtm/lead-drawer"
import { CellMap, type LeadPoint } from "@/components/need/cell-map"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiFetch } from "@/lib/api"
import { scoreColor } from "@/lib/grid"
import { countyName, type LeadCells, type LeadItem, type LeadPage, type View } from "@/lib/leads"

const PAGE_SIZE = 50
const POINTS_MIN_ZOOM = 13
const SORTS = [
  { key: "opportunity", label: "Opportunity, then use" },
  { key: "consumption", label: "Estimated use" },
  { key: "triggered_at", label: "Newest signal" },
] as const
type Sort = (typeof SORTS)[number]["key"]

type Filters = {
  view: View
  cells: string[]
  alert: boolean
  forecast: boolean
  gridStress: boolean
  newOnly: boolean
  sort: Sort
}
const EMPTY: Filters = { view: "leads", cells: [], alert: false, forecast: false, gridStress: false, newOnly: false, sort: "opportunity" }

type Points = { type: "FeatureCollection"; features: LeadPoint[]; aggregated?: boolean }

function params(f: Filters, bbox: string | null, extra: Record<string, string> = {}): URLSearchParams {
  const p = new URLSearchParams(extra)
  if (bbox && !f.cells.length) p.set("bbox", bbox) // clicked Cells define the area themselves
  if (f.view === "leads") p.set("leads_only", "true")
  f.cells.forEach((c) => p.append("cells", c))
  if (f.alert) p.set("alert", "true")
  if (f.forecast) p.set("forecast", "true")
  if (f.gridStress) p.set("grid_stress", "true")
  if (f.newOnly) p.set("new_only", "true")
  return p
}

function Score({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>
  return (
    <span className="rounded px-1.5 py-0.5 font-semibold tabular-nums" style={{ background: scoreColor(value) }}>
      {value.toFixed(0)}
    </span>
  )
}

function LiveFlags({ lead }: { lead: LeadItem }) {
  const c = lead.cell
  if (!c) return <span className="text-muted-foreground">—</span>
  return (
    <span className="flex gap-1">
      {c.active_alerts > 0 && <span className="rounded bg-red-600 px-1 text-[10px] text-white" title="Official NWS alert active">alert</span>}
      {c.forecast_level && <span className="rounded border border-dashed border-amber-500 px-1 text-[10px] text-amber-700" title="Forecast risk in 48 h (our reading of NWS data)">{c.forecast_level}</span>}
      {c.grid_stress_signals > 0 && <span className="rounded border border-dashed border-amber-500 px-1 text-[10px] text-amber-700" title="Grid stress (our reading of ERCOT data)">grid</span>}
      {c.active_alerts === 0 && !c.forecast_level && c.grid_stress_signals === 0 && <span className="text-muted-foreground">quiet</span>}
    </span>
  )
}

export function GtmPage({ initialLead = null }: { initialLead?: number | null }) {
  const [filters, setFilters] = React.useState<Filters>(EMPTY)
  const [bbox, setBbox] = React.useState<string | null>(null)
  const [zoom, setZoom] = React.useState(10)
  const [offset, setOffset] = React.useState(0)
  const [page, setPage] = React.useState<LeadPage | null>(null)
  const [points, setPoints] = React.useState<Points | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [openLead, setOpenLead] = React.useState<number | null>(initialLead)
  const [leadCells, setLeadCells] = React.useState<LeadCells | null>(null)

  const update = (patch: Partial<Filters>) => {
    setFilters((f) => ({ ...f, ...patch }))
    setOffset(0)
  }
  const toggleIn = (list: string[], value: string) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value])

  // The Lead Cells, for the map to dim the rest in the Leads view.
  React.useEffect(() => {
    if (filters.view !== "leads" || leadCells) return
    const controller = new AbortController()
    apiFetch<LeadCells>("/leads/cells", { signal: controller.signal })
      .then(setLeadCells)
      .catch(() => {})
    return () => controller.abort()
  }, [filters.view, leadCells])

  // The list: whatever the map and the chips currently allow.
  React.useEffect(() => {
    if (!bbox && !filters.cells.length) return
    const controller = new AbortController()
    const p = params(filters, bbox, { sort: filters.sort, limit: String(PAGE_SIZE), offset: String(offset) })
    async function load() {
      setLoading(true)
      try {
        const response = await apiFetch<LeadPage>(`/leads?${p}`, { signal: controller.signal })
        if (!controller.signal.aborted) setPage(response)
      } catch {
        // aborted or failed: keep the previous list
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    load()
    return () => controller.abort()
  }, [filters, bbox, offset])

  // Homes as points once zoomed in far enough, inside the same filter.
  const showPoints = zoom >= POINTS_MIN_ZOOM
  React.useEffect(() => {
    if (!bbox || !showPoints) return
    const controller = new AbortController()
    const p = params(filters, null, { bbox, zoom: String(Math.round(zoom)) })
    apiFetch<Points>(`/leads/geo?${p}`, { signal: controller.signal })
      .then((response) => setPoints(response.aggregated ? null : response))
      .catch(() => {})
    return () => controller.abort()
  }, [filters, bbox, zoom, showPoints])

  const chips: { key: string; label: string; clear: () => void }[] = []
  if (filters.cells.length) chips.push({ key: "cells", label: `${filters.cells.length} Cell${filters.cells.length > 1 ? "s" : ""} selected`, clear: () => update({ cells: [] }) })
  if (filters.alert) chips.push({ key: "alert", label: "Active NWS alert", clear: () => update({ alert: false }) })
  if (filters.forecast) chips.push({ key: "forecast", label: "Forecast risk 48 h", clear: () => update({ forecast: false }) })
  if (filters.gridStress) chips.push({ key: "grid", label: "ERCOT grid stress", clear: () => update({ gridStress: false }) })
  if (filters.newOnly) chips.push({ key: "new", label: "New this week", clear: () => update({ newOnly: false }) })

  const summary = page?.summary
  const total = page?.total ?? 0
  const pageEnd = Math.min(offset + PAGE_SIZE, total)

  // md+: the inset layout adds an 8px margin above and below the main panel (sidebar.tsx).
  return (
    <div className="flex h-[calc(100svh-var(--header-height))] flex-col md:h-[calc(100svh-var(--header-height)-1rem)]">
      <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2 text-xs">
        <Button size="sm" variant={filters.alert ? "secondary" : "outline"} onClick={() => update({ alert: !filters.alert })}>
          Active NWS alert{summary ? ` (${summary.alert.toLocaleString("en-US")})` : ""}
        </Button>
        <Button size="sm" variant={filters.forecast ? "secondary" : "outline"} onClick={() => update({ forecast: !filters.forecast })}>
          Forecast risk 48 h{summary ? ` (${summary.forecast.toLocaleString("en-US")})` : ""}
        </Button>
        <Button size="sm" variant={filters.gridStress ? "secondary" : "outline"} onClick={() => update({ gridStress: !filters.gridStress })}>
          ERCOT grid stress{summary ? ` (${summary.grid_stress.toLocaleString("en-US")})` : ""}
        </Button>
        <span className="mx-2 h-4 border-l" />
        <Button size="sm" variant={filters.newOnly ? "secondary" : "outline"} onClick={() => update({ newOnly: !filters.newOnly })}>
          New this week
        </Button>
      </div>

      {/* Active filters: shared by the map and the list, so they sit above both. */}
      {chips.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-b bg-primary/5 px-4 py-2 text-sm">
          {chips.map((c) => (
            <button
              key={c.key}
              type="button"
              onClick={c.clear}
              className="flex items-center gap-1.5 rounded-full bg-primary px-3 py-1 font-medium text-primary-foreground shadow-sm hover:bg-primary/85 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              title="Remove filter"
            >
              {c.label}
              <XIcon className="size-3.5" aria-label="Remove" />
            </button>
          ))}
          <Button size="sm" variant="ghost" className="ml-auto" onClick={() => update({ ...EMPTY, view: filters.view, sort: filters.sort })}>
            Clear all
          </Button>
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-5">
        <div className="min-h-[360px] lg:col-span-3">
          <CellMap
            className="h-full p-2"
            selectedCells={filters.cells}
            view={filters.view}
            onViewChange={(view) => update({ view })}
            leadCells={filters.view === "leads" ? (leadCells?.cells ?? []) : null}
            leadMinScore={leadCells?.min_score}
            onToggleCell={(h3, additive) => update({ cells: additive ? toggleIn(filters.cells, h3) : filters.cells.length === 1 && filters.cells[0] === h3 ? [] : [h3] })}
            onViewport={(box, z) => {
              setZoom(z)
              setBbox((prev) => (prev === box ? prev : box))
            }}
            points={showPoints ? points : null}
            onPointClick={setOpenLead}
            pointsMinZoom={POINTS_MIN_ZOOM}
          />
        </div>

        <div className="flex min-h-0 flex-col border-l lg:col-span-2">
          <div className="flex flex-wrap items-center gap-1 border-b px-3 py-2 text-xs">
            <span className="relative flex items-center">
              <ArrowUpDownIcon className="pointer-events-none absolute left-1.5 size-3.5 text-muted-foreground" aria-hidden />
              <select aria-label="Sort" className="rounded-md border bg-background py-0.5 pr-1 pl-6" value={filters.sort} onChange={(e) => update({ sort: e.target.value as Sort })}>
                {SORTS.map((s) => (
                  <option key={s.key} value={s.key}>{s.label}</option>
                ))}
              </select>
            </span>
            <span className="ml-1 font-medium">
              {loading ? "Loading…" : `${total.toLocaleString("en-US")} ${filters.view === "leads" ? "leads" : "homes"}`}
            </span>
            <span className="ml-auto">
              <ExportMenu query={params(filters, bbox, { sort: filters.sort })} disabled={!total} />
            </span>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {page && page.items.length === 0 && !loading ? (
              <p className="p-6 text-sm text-muted-foreground">
                {filters.view === "leads"
                  ? "No Lead Cells in this view. Leads are the top-Opportunity Cells of Harris County (Houston) and Travis County (Austin); pan there, clear a filter or switch to Overview."
                  : "No homes in this view. Homes are loaded for Harris County (Houston) and Austin Energy homes in Travis County (Austin); pan there or clear a filter."}
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow className="text-xs">
                    <TableHead>Home</TableHead>
                    <TableHead className="text-right" title="How promising this home's area is, 0–100: likely buyers, backup-power need, and a boost right after a storm">Opportunity</TableHead>
                    <TableHead>Now</TableHead>
                    <TableHead className="text-right" title="Estimated electricity use, kWh per year">Use</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {page?.items.map((lead) => (
                    <TableRow
                      key={lead.id}
                      role="button"
                      tabIndex={0}
                      className="cursor-pointer text-xs focus-visible:outline-2 [&>td]:py-3.5 focus-visible:outline-ring"
                      onClick={() => setOpenLead(lead.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault()
                          setOpenLead(lead.id)
                        }
                      }}
                    >
                      <TableCell>
                        <div className="flex items-start gap-1.5">
                          <MapPinIcon className="mt-0.5 size-3.5 shrink-0 text-primary" aria-hidden />
                          <div className="flex min-w-0 flex-col gap-1">
                            <div className="font-semibold">{lead.address ?? `Lead ${lead.id}`}</div>
                            <div className="text-muted-foreground">
                              {[lead.city, lead.zip, countyName(lead.county)].filter(Boolean).join(" · ")}
                            </div>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="text-right"><Score value={lead.cell?.opportunity_score} /></TableCell>
                      <TableCell><LiveFlags lead={lead} /></TableCell>
                      <TableCell className="text-right tabular-nums">{lead.annual_kwh ? Math.round(lead.annual_kwh).toLocaleString("en-US") : "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>

          <div className="flex items-center justify-between border-t px-3 py-2 text-xs">
            <span className="text-muted-foreground">{total ? `${offset + 1}–${pageEnd} of ${total.toLocaleString("en-US")}` : ""}</span>
            <span className="flex gap-1">
              <Button size="sm" variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</Button>
              <Button size="sm" variant="outline" disabled={pageEnd >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</Button>
            </span>
          </div>
        </div>
      </div>

      <LeadDrawer id={openLead} onClose={() => setOpenLead(null)} />
    </div>
  )
}
