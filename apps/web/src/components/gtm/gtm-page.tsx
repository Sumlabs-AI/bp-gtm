"use client"

import * as React from "react"

import { LeadDrawer } from "@/components/gtm/lead-drawer"
import { CellMap, type LeadPoint } from "@/components/need/cell-map"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiFetch } from "@/lib/api"
import { scoreColor } from "@/lib/grid"
import { STATUS_LABELS, formatLeadMoney, type LeadItem, type LeadPage, type LeadStatus } from "@/lib/leads"
import { NEED_BANDS } from "@/lib/need"

const PAGE_SIZE = 50
const POINTS_MIN_ZOOM = 13
const SORTS = [
  { key: "need", label: "Need, then use" },
  { key: "priority", label: "Expected Value" },
  { key: "consumption", label: "Estimated use" },
  { key: "triggered_at", label: "Newest signal" },
] as const
type Sort = (typeof SORTS)[number]["key"]

type Filters = {
  bands: string[]
  cells: string[]
  alert: boolean
  forecast: boolean
  gridStress: boolean
  newOnly: boolean
  status: LeadStatus | ""
  sort: Sort
}
const EMPTY: Filters = { bands: [], cells: [], alert: false, forecast: false, gridStress: false, newOnly: false, status: "", sort: "need" }

type Points = { type: "FeatureCollection"; features: LeadPoint[]; aggregated?: boolean }

function params(f: Filters, bbox: string | null, extra: Record<string, string> = {}): URLSearchParams {
  const p = new URLSearchParams(extra)
  if (bbox && !f.cells.length) p.set("bbox", bbox) // clicked Cells define the area themselves
  f.cells.forEach((c) => p.append("cells", c))
  f.bands.forEach((b) => p.append("need_band", b))
  if (f.alert) p.set("alert", "true")
  if (f.forecast) p.set("forecast", "true")
  if (f.gridStress) p.set("grid_stress", "true")
  if (f.newOnly) p.set("new_only", "true")
  if (f.status) p.set("status", f.status)
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

export function GtmPage() {
  const [filters, setFilters] = React.useState<Filters>(EMPTY)
  const [bbox, setBbox] = React.useState<string | null>(null)
  const [zoom, setZoom] = React.useState(10)
  const [offset, setOffset] = React.useState(0)
  const [page, setPage] = React.useState<LeadPage | null>(null)
  const [points, setPoints] = React.useState<Points | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [openLead, setOpenLead] = React.useState<number | null>(null)

  const update = (patch: Partial<Filters>) => {
    setFilters((f) => ({ ...f, ...patch }))
    setOffset(0)
  }
  const toggleIn = (list: string[], value: string) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value])

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

  const chips: { label: string; clear: () => void }[] = []
  if (filters.cells.length) chips.push({ label: `${filters.cells.length} Cell${filters.cells.length > 1 ? "s" : ""} selected`, clear: () => update({ cells: [] }) })
  filters.bands.forEach((b) => chips.push({ label: `Need ${NEED_BANDS.find((x) => x.key === b)?.label}`, clear: () => update({ bands: filters.bands.filter((x) => x !== b) }) }))
  if (filters.alert) chips.push({ label: "Active NWS alert", clear: () => update({ alert: false }) })
  if (filters.forecast) chips.push({ label: "Forecast risk 48 h", clear: () => update({ forecast: false }) })
  if (filters.gridStress) chips.push({ label: "ERCOT grid stress", clear: () => update({ gridStress: false }) })
  if (filters.newOnly) chips.push({ label: "New this week", clear: () => update({ newOnly: false }) })
  if (filters.status) chips.push({ label: STATUS_LABELS[filters.status], clear: () => update({ status: "" }) })

  const summary = page?.summary
  const total = page?.total ?? 0
  const pageEnd = Math.min(offset + PAGE_SIZE, total)

  return (
    <div className="flex h-[calc(100vh-var(--header-height))] flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2 text-xs">
        <span className="font-medium">Why now</span>
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
        <select
          className="rounded-md border bg-background px-2 py-1"
          value={filters.status}
          onChange={(e) => update({ status: e.target.value as LeadStatus | "" })}
        >
          <option value="">Any status</option>
          {(Object.keys(STATUS_LABELS) as LeadStatus[]).map((s) => (
            <option key={s} value={s}>{STATUS_LABELS[s]}</option>
          ))}
        </select>
        <span className="ml-auto text-muted-foreground">
          {summary?.grid_state && (
            <Badge variant={summary.grid_state === "normal" ? "outline" : "destructive"} className="mr-2">
              ERCOT {summary.grid_state}
            </Badge>
          )}
          Leads are loaded for Harris County (Houston); Travis shows Need only.
        </span>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-5">
        <div className="min-h-[360px] lg:col-span-3">
          <CellMap
            className="h-full p-2"
            selectedCells={filters.cells}
            onToggleCell={(h3, additive) => update({ cells: additive ? toggleIn(filters.cells, h3) : filters.cells.length === 1 && filters.cells[0] === h3 ? [] : [h3] })}
            bands={filters.bands}
            onToggleBand={(b) => update({ bands: toggleIn(filters.bands, b) })}
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
            <span className="font-medium">
              {loading ? "Loading…" : `${total.toLocaleString("en-US")} leads`}
            </span>
            {summary?.avg_baseline_need !== null && summary?.avg_baseline_need !== undefined && (
              <span className="text-muted-foreground">· avg Baseline Need {summary.avg_baseline_need.toFixed(0)}</span>
            )}
            <span className="ml-auto flex items-center gap-1">
              <span className="text-muted-foreground">sort</span>
              <select className="rounded-md border bg-background px-1 py-0.5" value={filters.sort} onChange={(e) => update({ sort: e.target.value as Sort })}>
                {SORTS.map((s) => (
                  <option key={s.key} value={s.key}>{s.label}</option>
                ))}
              </select>
            </span>
            {chips.length > 0 && (
              <div className="flex w-full flex-wrap gap-1 pt-1">
                <span className="text-muted-foreground">in view ·</span>
                {chips.map((c) => (
                  <button key={c.label} type="button" onClick={c.clear} className="rounded-full border px-2 py-0.5 hover:bg-muted" title="Remove filter">
                    {c.label} ×
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {page && page.items.length === 0 && !loading ? (
              <p className="p-6 text-sm text-muted-foreground">
                No leads in this view. Leads are loaded for Harris County (Houston) only; pan there or clear a filter.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow className="text-xs">
                    <TableHead>Home</TableHead>
                    <TableHead className="text-right" title="Baseline Need of the home's Cell (Texas percentile)">Need</TableHead>
                    <TableHead className="text-right" title="ML propensity of the home's Cell (when imported)">Prop.</TableHead>
                    <TableHead>Now</TableHead>
                    <TableHead className="text-right" title="Estimated electricity use, kWh per year">Use</TableHead>
                    <TableHead className="text-right" title="Expected Value, $ per year">EV</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {page?.items.map((lead) => (
                    <TableRow key={lead.id} className="cursor-pointer text-xs" onClick={() => setOpenLead(lead.id)}>
                      <TableCell>
                        <div className="font-medium">{lead.address ?? `Lead ${lead.id}`}</div>
                        <div className="text-muted-foreground">{lead.zip}</div>
                      </TableCell>
                      <TableCell className="text-right"><Score value={lead.cell?.baseline_need} /></TableCell>
                      <TableCell className="text-right"><Score value={lead.cell?.propensity_score} /></TableCell>
                      <TableCell><LiveFlags lead={lead} /></TableCell>
                      <TableCell className="text-right tabular-nums">{lead.annual_kwh ? Math.round(lead.annual_kwh).toLocaleString("en-US") : "—"}</TableCell>
                      <TableCell className="text-right tabular-nums">{lead.expected_value !== null ? formatLeadMoney(lead.expected_value) : "—"}</TableCell>
                      <TableCell>{STATUS_LABELS[lead.status]}</TableCell>
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
