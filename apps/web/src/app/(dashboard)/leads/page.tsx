import Link from "next/link"
import { connection } from "next/server"

import { LeadsMap } from "@/components/leads/leads-map"
import { PriorityHelp } from "@/components/leads/priority-help"
import { SiteHeader } from "@/components/site-header"
import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"
import { Field, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiFetch } from "@/lib/api"
import type { ZoneSummary } from "@/lib/grid"
import { BATTERY_SIZES, SIGNAL_LABELS, STATUS_LABELS, formatKwh, formatLeadMoney, signalLabel, valueBasis, type LeadItem, type LeadPage, type LeadSignal, type LeadStatus, type LeadSummary } from "@/lib/leads"
import { cn } from "@/lib/utils"

export const metadata = { title: "Leads" }

const PAGE_SIZE = 50
const SIGNALS = Object.keys(SIGNAL_LABELS) as LeadSignal[]
const SCORES = [0, 30, 40, 50]
const STATUSES: LeadStatus[] = ["new", "reviewed", "qualified", "excluded"]
const SORTS = ["priority", "score", "value", "triggered_at"] as const

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value
}

function recentTrigger(triggeredAt: string | null, trigger: string | null): string {
  if (!triggeredAt) return "None in 7 days"
  const age = Date.now() - new Date(triggeredAt).getTime()
  if (!Number.isFinite(age) || age < 0 || age > 7 * 24 * 60 * 60 * 1000) return "None in 7 days"
  const days = Math.floor(age / (24 * 60 * 60 * 1000))
  const when = days === 0 ? "today" : days === 1 ? "yesterday" : `${days} days ago`
  return `${trigger ? signalLabel(trigger) : "Newly eligible"} · detected ${when}`
}

function BatteryValues({ lead }: { lead: LeadItem }) {
  return (
    <div className="grid grid-cols-3 gap-2 text-xs tabular-nums">
      {BATTERY_SIZES.map((size) => (
        <div key={size} className={cn("flex flex-col gap-1 rounded-md p-2", size === lead.recommended_kwh && "bg-muted font-semibold")}>
          <span>{size} kWh</span>
          <span>{lead.battery_values ? formatLeadMoney(lead.battery_values[size].value) : "Unavailable"}</span>
          {size === lead.recommended_kwh && <span>Suggested</span>}
        </div>
      ))}
    </div>
  )
}

function RecordedSignals({ lead }: { lead: LeadItem }) {
  const recordedSignals = SIGNALS.filter((signal) => lead.signals.includes(signal))
  if (recordedSignals.length === 0) return <span className="text-muted-foreground">—</span>

  return (
    <div className="flex flex-wrap gap-1">
      {recordedSignals.map((signal) => (
        <Badge key={signal} variant="secondary">{SIGNAL_LABELS[signal]}</Badge>
      ))}
    </div>
  )
}

export default async function LeadsPage(props: PageProps<"/leads">) {
  await connection()
  const query = await props.searchParams
  const minScore = SCORES.find((score) => String(score) === first(query.min_score)) ?? 0
  const requestedSignals = Array.isArray(query.signals) ? query.signals : query.signals ? [query.signals] : []
  const signals = SIGNALS.filter((signal) => requestedSignals.includes(signal))
  const newOnly = first(query.new_only) === "true"
  const zip = (first(query.zip) ?? "").trim()
  const zone = (first(query.zone) ?? "").trim()
  const requestedStatus = first(query.status)
  const status = requestedStatus === "all" ? "all" : STATUSES.find((value) => value === requestedStatus) ?? "new"
  const sort = SORTS.find((value) => value === first(query.sort)) ?? "priority"
  const view = first(query.view) === "map" ? "map" : "list"
  const requestedOffset = Number(first(query.offset) ?? 0)
  const offset = Number.isSafeInteger(requestedOffset) && requestedOffset >= 0 ? Math.floor(requestedOffset / PAGE_SIZE) * PAGE_SIZE : 0

  const filters = new URLSearchParams({ status, sort })
  if (minScore) filters.set("min_score", String(minScore))
  signals.forEach((signal) => filters.append("signals", signal))
  if (newOnly) filters.set("new_only", "true")
  if (zip) filters.set("zip", zip)
  if (zone) filters.set("zone", zone)

  const listQuery = new URLSearchParams(filters)
  if (status === "all") listQuery.delete("status")
  listQuery.set("limit", String(view === "map" ? 1 : PAGE_SIZE))
  if (view === "list") listQuery.set("offset", String(offset))
  const [summary, page, zones] = await Promise.all([
    apiFetch<LeadSummary>("/leads/summary"),
    apiFetch<LeadPage>(`/leads?${listQuery}`),
    zone ? apiFetch<ZoneSummary[]>("/grid/zones").catch(() => []) : [],
  ])
  const firstBatteryValue = page.items.flatMap((lead) => Object.values(lead.battery_values ?? {}))[0]
  const zoneName = zones.find((item) => item.code === zone)?.name ?? zone

  function listHref(nextView = view, nextOffset = offset) {
    const params = new URLSearchParams(filters)
    params.set("view", nextView)
    if (nextOffset > 0) params.set("offset", String(nextOffset))
    return `/leads?${params}`
  }

  const backHref = listHref()
  const clearQuery = new URLSearchParams({ status, view })
  const allLeadsQuery = new URLSearchParams({ status: "all", view })
  if (zone) {
    clearQuery.set("zone", zone)
    allLeadsQuery.set("zone", zone)
  }
  const clearHref = `/leads?${clearQuery}`
  const allLeadsHref = `/leads?${allLeadsQuery}`
  const recentQuery = new URLSearchParams(allLeadsQuery)
  recentQuery.set("new_only", "true")
  const clearZoneQuery = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (key === "zone" || value === undefined) continue
    for (const item of Array.isArray(value) ? value : [value]) clearZoneQuery.append(key, item)
  }
  const clearZoneHref = `/leads${clearZoneQuery.size ? `?${clearZoneQuery}` : ""}`
  const detailHref = (id: number) => `/leads/${id}?${new URLSearchParams({ back: backHref })}`

  return (
    <>
      <SiteHeader title="Leads" />
      <div className="flex min-w-0 flex-col gap-5 px-4 py-4 md:py-6 lg:px-6">
        <p className="text-sm text-muted-foreground">Review homes Base can serve in Harris County, ranked by Priority value.</p>

        <form key={backHref} action="/leads" method="get" className="flex flex-col gap-3">
          <input type="hidden" name="view" value={view} />
          {zone && <>
            <input type="hidden" name="zone" value={zone} />
            <Badge variant="secondary" className="max-w-full">
              <span className="truncate">Load Zone: {zoneName}</span>
              <Link href={clearZoneHref} aria-label="Clear Load Zone filter" className="shrink-0 underline underline-offset-2">Clear</Link>
            </Badge>
          </>}
          <FieldGroup className="grid gap-3 sm:grid-cols-2 xl:grid-cols-[7rem_7rem_10rem_1fr_auto] xl:items-end">
            <Field>
              <FieldLabel htmlFor="zip">ZIP</FieldLabel>
              <Input id="zip" name="zip" defaultValue={zip} inputMode="numeric" placeholder="Any ZIP" />
            </Field>
            <Field>
              <FieldLabel htmlFor="min-score">Minimum fit</FieldLabel>
              <NativeSelect id="min-score" name="min_score" defaultValue={String(minScore)} className="w-full">
                {SCORES.map((score) => <NativeSelectOption key={score} value={String(score)}>{score === 0 ? "Any" : `${score}+`}</NativeSelectOption>)}
              </NativeSelect>
            </Field>
            <Field>
              <FieldLabel htmlFor="status">Review status</FieldLabel>
              <NativeSelect id="status" name="status" defaultValue={status} className="w-full">
                <NativeSelectOption value="all">All leads</NativeSelectOption>
                {STATUSES.map((value) => <NativeSelectOption key={value} value={value}>{STATUS_LABELS[value]}</NativeSelectOption>)}
              </NativeSelect>
            </Field>
            <Field>
              <FieldLabel htmlFor="sort">Sort by</FieldLabel>
              <NativeSelect id="sort" name="sort" defaultValue={sort} className="w-full">
                <NativeSelectOption value="priority">Priority value · highest first</NativeSelectOption>
                <NativeSelectOption value="score">Fit · highest first</NativeSelectOption>
                <NativeSelectOption value="value">Grid value · highest first</NativeSelectOption>
                <NativeSelectOption value="triggered_at">Latest signal</NativeSelectOption>
              </NativeSelect>
            </Field>
            <div className="flex items-center gap-2">
              <Button type="submit">Apply</Button>
              <Link href={clearHref} className={buttonVariants({ variant: "ghost" })}>Clear filters</Link>
            </div>
          </FieldGroup>
          <details open={signals.length > 0 || newOnly}>
            <summary className="w-fit cursor-pointer text-sm font-medium">Signals &amp; timing{signals.length + Number(newOnly) > 0 ? ` (${signals.length + Number(newOnly)} active)` : ""}</summary>
            <FieldSet className="mt-3">
              <FieldLegend variant="label">Match all selected signals</FieldLegend>
              <div className="flex flex-wrap gap-2">
                {SIGNALS.map((signal) => (
                  <label key={signal} className="flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 text-xs has-[:checked]:border-primary has-[:checked]:bg-muted has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-ring">
                    <input type="checkbox" name="signals" value={signal} defaultChecked={signals.includes(signal)} className="accent-primary" />
                    {SIGNAL_LABELS[signal]}
                  </label>
                ))}
                <label className="flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 text-xs has-[:checked]:border-primary has-[:checked]:bg-muted has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-ring">
                  <input type="checkbox" name="new_only" value="true" defaultChecked={newOnly} className="accent-primary" />
                  Recent signals · 7 days
                </label>
              </div>
            </FieldSet>
          </details>
        </form>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-col gap-2">
            <p className="text-sm"><strong>{page.total.toLocaleString("en-US")} leads match</strong> <span className="text-muted-foreground">· Scores updated {summary.last_scored_at ? new Date(summary.last_scored_at).toLocaleDateString("en-US", { timeZone: "America/Chicago" }) : "not yet"}</span></p>
            <div className="flex flex-wrap items-center gap-2">
              <Link href={`/leads?${recentQuery}`} className={buttonVariants({ variant: "outline", size: "sm", className: "rounded-full" })}>Recent signals · 7 days{!zone && ` (${summary.new_this_week.toLocaleString("en-US")})`}</Link>
              <span className="text-xs text-muted-foreground">{zone ? zoneName : "All Harris County"} · all statuses</span>
            </div>
          </div>
          <nav aria-label="Lead view" className="flex gap-2">
            <Link href={listHref("list")} className={buttonVariants({ variant: view === "list" ? "secondary" : "outline", size: "sm" })} aria-current={view === "list" ? "page" : undefined}>List</Link>
            <Link href={listHref("map")} className={buttonVariants({ variant: view === "map" ? "secondary" : "outline", size: "sm" })} aria-current={view === "map" ? "page" : undefined}>Map</Link>
          </nav>
        </div>
        <PriorityHelp />

        {summary.leads === 0 ? (
          <Empty><EmptyHeader><EmptyTitle>No lead data yet</EmptyTitle><EmptyDescription>Leads will appear after source data has been refreshed and scored.</EmptyDescription></EmptyHeader><EmptyContent><Link href="/data" className={buttonVariants({ variant: "outline" })}>View data sources</Link></EmptyContent></Empty>
        ) : page.total === 0 ? (
          <Empty><EmptyHeader><EmptyTitle>No leads match these filters</EmptyTitle><EmptyDescription>Try a lower minimum fit or fewer signals. All leads includes homes already reviewed.</EmptyDescription></EmptyHeader><EmptyContent><Link href={clearHref} className={buttonVariants({ variant: "outline" })}>Clear filters</Link><Link href={allLeadsHref} className={buttonVariants({ variant: "ghost" })}>View all leads</Link></EmptyContent></Empty>
        ) : view === "map" ? (
          <LeadsMap key={filters.toString()} filters={{ minScore, signals, newOnly, zip, zone: zone || undefined, status: status === "all" ? undefined : status }} backHref={backHref} className="h-[min(65vh,600px)] min-h-96" />
        ) : (
          <>
            <p className="text-xs text-muted-foreground">Historical grid value to Base · $/year · {valueBasis(firstBatteryValue)}. Suggested size is highlighted. Only recorded signals are shown; — = none found in available records.</p>
            <div className="hidden rounded-xl border xl:block">
              <Table>
                <TableHeader><TableRow><TableHead>Address</TableHead><TableHead>Priority value / Fit</TableHead><TableHead>Historical grid value to Base</TableHead><TableHead>Recorded signals</TableHead><TableHead>Recent signal</TableHead><TableHead>Review status</TableHead></TableRow></TableHeader>
                <TableBody>
                  {page.items.map((lead) => (
                    <TableRow key={lead.id}>
                      <TableCell className="min-w-44 max-w-60 whitespace-normal">
                        <Link href={detailHref(lead.id)} className="font-medium text-primary hover:underline">{lead.address ?? `Lead ${lead.id}`}</Link>
                        <span className="block text-xs text-muted-foreground">{[lead.city, lead.zip].filter(Boolean).join(" · ") || "Location unavailable"}</span>
                        <span className="block text-xs text-muted-foreground tabular-nums">{lead.annual_kwh === null ? "Est. use unavailable" : `Est. use ≈ ${formatKwh(Math.round(lead.annual_kwh / 120) * 10)}/mo`}</span>
                        <span className="line-clamp-1 text-xs text-muted-foreground" title={lead.reasons}>{lead.reasons}</span>
                      </TableCell>
                      <TableCell className="tabular-nums"><span className="block font-semibold">{lead.expected_value === null ? "Unavailable" : formatLeadMoney(lead.expected_value)}</span><span className="text-xs text-muted-foreground">Fit {lead.score.toFixed(0)} / 100</span></TableCell>
                      <TableCell className="min-w-60"><BatteryValues lead={lead} /></TableCell>
                      <TableCell><RecordedSignals lead={lead} /></TableCell>
                      <TableCell className="max-w-40 whitespace-normal text-xs text-muted-foreground">{recentTrigger(lead.triggered_at, lead.trigger)}</TableCell>
                      <TableCell><Badge variant="outline">{STATUS_LABELS[lead.status]}</Badge></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <div className="flex flex-col gap-3 xl:hidden">
              {page.items.map((lead) => (
                <Card key={lead.id} size="sm">
                  <CardHeader>
                    <div className="flex flex-wrap items-start justify-between gap-2"><CardTitle><Link href={detailHref(lead.id)} className="text-primary hover:underline">{lead.address ?? `Lead ${lead.id}`}</Link></CardTitle><Badge variant="outline">{STATUS_LABELS[lead.status]}</Badge></div>
                    <p className="text-xs text-muted-foreground">{[lead.city, lead.zip].filter(Boolean).join(" · ") || "Location unavailable"}</p>
                    <p className="text-xs text-muted-foreground tabular-nums">{lead.annual_kwh === null ? "Est. use unavailable" : `Est. use ≈ ${formatKwh(Math.round(lead.annual_kwh / 120) * 10)}/mo`}</p>
                    <p className="line-clamp-1 text-xs text-muted-foreground">{lead.reasons}</p>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-3">
                    <div className="flex flex-wrap justify-between gap-2 text-sm tabular-nums"><span>Priority value <strong>{lead.expected_value === null ? "Unavailable" : formatLeadMoney(lead.expected_value)}</strong></span><span>Fit {lead.score.toFixed(0)} / 100</span></div>
                    <div><p className="mb-1 text-xs text-muted-foreground">Historical grid value to Base · $/year · {valueBasis(Object.values(lead.battery_values ?? {})[0])}. Suggested size is highlighted.</p><BatteryValues lead={lead} /></div>
                    <RecordedSignals lead={lead} />
                    <p className="text-xs text-muted-foreground">Recent signal: {recentTrigger(lead.triggered_at, lead.trigger)}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
            {page.items.length === 0 && <Empty><EmptyHeader><EmptyTitle>No leads on this page</EmptyTitle><EmptyDescription>The results may have changed since your last visit.</EmptyDescription></EmptyHeader><EmptyContent><Link href={listHref("list", 0)} className={buttonVariants({ variant: "outline" })}>Return to first page</Link></EmptyContent></Empty>}
            <nav aria-label="Results pages" className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-muted-foreground">Showing {page.items.length ? offset + 1 : 0}–{page.items.length ? Math.min(offset + page.items.length, page.total) : 0} of {page.total.toLocaleString("en-US")}</p>
              <div className="flex gap-2">
                {offset > 0 ? <Link href={listHref("list", Math.max(0, offset - PAGE_SIZE))} className={buttonVariants({ variant: "outline", size: "sm" })}>Previous</Link> : <Button variant="outline" size="sm" disabled>Previous</Button>}
                {offset + PAGE_SIZE < page.total ? <Link href={listHref("list", offset + PAGE_SIZE)} className={buttonVariants({ variant: "outline", size: "sm" })}>Next</Link> : <Button variant="outline" size="sm" disabled>Next</Button>}
              </div>
            </nav>
          </>
        )}
      </div>
    </>
  )
}
