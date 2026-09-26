import Link from "next/link"
import { connection } from "next/server"

import { LeadsMap } from "@/components/leads/leads-map"
import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiFetch } from "@/lib/api"
import { scoreColor } from "@/lib/grid"
import { SIGNAL_LABELS, signalLabel, type LeadPage, type LeadSignal, type LeadStatus, type LeadSummary } from "@/lib/leads"

const PAGE_SIZE = 50
const SIGNALS = Object.keys(SIGNAL_LABELS) as LeadSignal[]
const SCORES = [0, 50, 70, 85]
const STATUSES: LeadStatus[] = ["new", "reviewed", "qualified", "excluded"]
const SORTS = ["priority", "score", "value", "triggered_at"] as const
const BATTERY_SIZES = ["25", "40", "50"] as const
const formatDollars = (value: number) => `$${Math.round(value).toLocaleString("en-US")}`

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value
}

function recentTrigger(triggeredAt: string | null, trigger: string | null): string | null {
  if (!triggeredAt) return null
  const age = Date.now() - new Date(triggeredAt).getTime()
  if (!Number.isFinite(age) || age < 0 || age > 7 * 24 * 60 * 60 * 1000) return null
  const days = Math.floor(age / (24 * 60 * 60 * 1000))
  const when = days === 0 ? "today" : days === 1 ? "yesterday" : `${days} days ago`
  return `${trigger ? signalLabel(trigger) : "New lead"} · ${when}`
}

export default async function LeadsPage(props: PageProps<"/leads">) {
  await connection()
  const query = await props.searchParams
  const minScore = SCORES.find((score) => String(score) === first(query.min_score)) ?? 0
  const requestedSignals = Array.isArray(query.signals)
    ? query.signals
    : query.signals ? [query.signals] : []
  const signals = SIGNALS.filter((signal) => requestedSignals.includes(signal))
  const newOnly = first(query.new_only) === "true"
  const zip = (first(query.zip) ?? "").trim()
  const requestedStatus = first(query.status)
  const status = STATUSES.find((value) => value === requestedStatus)
  const sort = SORTS.find((value) => value === first(query.sort)) ?? "priority"
  const view = first(query.view) === "map" ? "map" : "list"
  const requestedOffset = Number(first(query.offset) ?? 0)
  const offset = Number.isSafeInteger(requestedOffset) && requestedOffset >= 0
    ? Math.floor(requestedOffset / PAGE_SIZE) * PAGE_SIZE
    : 0

  const filters = new URLSearchParams()
  if (minScore) filters.set("min_score", String(minScore))
  signals.forEach((signal) => filters.append("signals", signal))
  if (newOnly) filters.set("new_only", "true")
  if (zip) filters.set("zip", zip)
  if (status) filters.set("status", status)
  if (sort !== "priority") filters.set("sort", sort)

  const listQuery = new URLSearchParams(filters)
  listQuery.set("limit", String(PAGE_SIZE))
  listQuery.set("offset", String(offset))
  const [summary, page] = await Promise.all([
    apiFetch<LeadSummary>("/leads/summary"),
    view === "list" ? apiFetch<LeadPage>(`/leads?${listQuery}`) : Promise.resolve(null),
  ])

  function viewHref(nextView: "list" | "map") {
    const params = new URLSearchParams(filters)
    if (offset > 0) params.set("offset", String(offset))
    if (nextView === "map") params.set("view", "map")
    return `/leads${params.size ? `?${params}` : ""}`
  }

  function pageHref(nextOffset: number) {
    const params = new URLSearchParams(filters)
    if (nextOffset > 0) params.set("offset", String(nextOffset))
    return `/leads${params.size ? `?${params}` : ""}`
  }

  return (
    <div className="flex flex-col gap-6 px-4 py-4 md:py-6 lg:px-6">
      <div className="flex flex-col gap-2">
        <h2 className="text-2xl font-semibold tracking-tight">Residential leads</h2>
        <p className="max-w-4xl text-sm text-muted-foreground">
          Single-family, owner-occupied homes Base can serve in the Harris County pilot, ranked by priority value.
        </p>
        <p className="text-xs text-muted-foreground">Fit score × realistic battery value. A ranking index, not a revenue forecast.</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ["Leads", summary.leads],
          ["New this week", summary.new_this_week],
          ["With solar", summary.by_signal.solar],
          ["New owners", summary.by_signal.new_owner],
        ].map(([label, value]) => (
          <Card key={label} size="sm">
            <CardHeader>
              <CardDescription>{label}</CardDescription>
              <CardTitle className="text-2xl tabular-nums">{Number(value).toLocaleString("en-US")}</CardTitle>
            </CardHeader>
          </Card>
        ))}
      </div>

      <nav aria-label="Lead view" className="flex justify-end gap-2">
        <Link href={viewHref("list")} className={buttonVariants({ variant: view === "list" ? "secondary" : "outline", size: "sm" })} aria-current={view === "list" ? "page" : undefined}>List</Link>
        <Link href={viewHref("map")} className={buttonVariants({ variant: view === "map" ? "secondary" : "outline", size: "sm" })} aria-current={view === "map" ? "page" : undefined}>Map</Link>
      </nav>

      {summary.leads === 0 && view === "list" ? (
        <Card>
          <CardHeader>
            <CardTitle>No lead data yet</CardTitle>
            <CardDescription>Load the Harris County source data, then score the eligible homes to see leads here.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <code className="block w-fit rounded-md bg-muted px-3 py-2">docker compose exec api python -m app.leads refresh</code>
            <code className="block w-fit rounded-md bg-muted px-3 py-2">docker compose exec api python -m app.leads score</code>
          </CardContent>
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Filter leads</CardTitle>
            </CardHeader>
            <CardContent>
              <form action="/leads" method="get" className="flex flex-col gap-4">
                <input type="hidden" name="view" value={view} />
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="min-score">Minimum score</Label>
                    <Select name="min_score" defaultValue={String(minScore)}>
                      <SelectTrigger id="min-score" className="w-full"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          {SCORES.map((score) => <SelectItem key={score} value={String(score)}>{score === 0 ? "Any score" : `${score}+`}</SelectItem>)}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="zip">ZIP</Label>
                    <Input id="zip" name="zip" defaultValue={zip} inputMode="numeric" placeholder="Any ZIP" />
                  </div>
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="status">Status</Label>
                    <Select name="status" defaultValue={status ?? "all"}>
                      <SelectTrigger id="status" className="w-full"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          <SelectItem value="all">All statuses</SelectItem>
                          {STATUSES.map((value) => <SelectItem key={value} value={value}>{value[0].toUpperCase() + value.slice(1)}</SelectItem>)}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="sort">Sort by</Label>
                    <Select name="sort" defaultValue={sort}>
                      <SelectTrigger id="sort" className="w-full"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          <SelectItem value="priority">Priority (fit × value)</SelectItem>
                          <SelectItem value="score">Fit score</SelectItem>
                          <SelectItem value="value">Battery value</SelectItem>
                          <SelectItem value="triggered_at">Newest signal</SelectItem>
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex items-end">
                    <Button type="submit" className="w-full">Apply filters</Button>
                  </div>
                </div>
                <Separator />
                <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
                  <span className="text-sm font-medium">Signals</span>
                  {SIGNALS.map((signal) => (
                    <Label key={signal} htmlFor={`signal-${signal}`} className="font-normal">
                      <Checkbox id={`signal-${signal}`} name="signals" value={signal} defaultChecked={signals.includes(signal)} />
                      {SIGNAL_LABELS[signal]}
                    </Label>
                  ))}
                  <Label htmlFor="new-only" className="font-normal">
                    <Checkbox id="new-only" name="new_only" value="true" defaultChecked={newOnly} />
                    New this week
                  </Label>
                </div>
              </form>
            </CardContent>
          </Card>

          {view === "map" ? (
            <LeadsMap filters={{ minScore, signals, newOnly, zip, status }} className="h-[600px]" />
          ) : page && <Card>
            <CardHeader>
              <CardTitle>Leads</CardTitle>
              <CardDescription>Showing {page.items.length ? offset + 1 : 0}–{Math.min(offset + page.items.length, page.total)} of {page.total.toLocaleString("en-US")}</CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Priority value ($/yr)</TableHead>
                    <TableHead>Fit</TableHead>
                    <TableHead>Address</TableHead>
                    <TableHead>Battery value ($/yr)</TableHead>
                    <TableHead>Signals</TableHead>
                    <TableHead>Why now</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {page.items.map((lead) => {
                    const batteryValues = lead.battery_values
                    return (
                      <TableRow key={lead.id}>
                        <TableCell className="tabular-nums">
                          {lead.expected_value === null ? (
                            <span className="text-xs text-muted-foreground">Value unavailable</span>
                          ) : (
                            <span className="font-semibold">{formatDollars(lead.expected_value)}</span>
                          )}
                        </TableCell>
                        <TableCell>
                          <Badge className="tabular-nums" style={{ background: scoreColor(lead.score) }}>
                            {lead.score.toFixed(0)}
                          </Badge>
                        </TableCell>
                        <TableCell className="max-w-64 min-w-48 whitespace-normal">
                          <Link href={`/leads/${lead.id}`} className="font-medium text-primary hover:underline">
                            {lead.address ?? `Lead ${lead.id}`}
                          </Link>
                          <span className="block text-xs text-muted-foreground">
                            {[lead.city, lead.zip].filter(Boolean).join(" · ") || "Location unavailable"}
                          </span>
                          {lead.reasons && <span className="block text-xs text-muted-foreground">{lead.reasons}</span>}
                        </TableCell>
                        <TableCell>
                          {batteryValues ? (
                            <div className="flex min-w-60 flex-wrap items-center gap-x-2 gap-y-1 text-xs tabular-nums">
                              {BATTERY_SIZES.map((size) => (
                                <span key={size} className={Number(size) === lead.recommended_kwh ? "font-semibold" : undefined}>
                                  {size} kWh {formatDollars(batteryValues[size].value)}
                                  {Number(size) === lead.recommended_kwh && <Badge variant="secondary" className="ml-1">Pitch</Badge>}
                                </span>
                              ))}
                            </div>
                          ) : <span className="text-xs text-muted-foreground">Value unavailable</span>}
                        </TableCell>
                        <TableCell>
                          <div className="flex max-w-52 flex-wrap gap-1">
                            {lead.signals.length ? lead.signals.map((signal) => (
                              <Badge key={signal} variant="secondary">{signalLabel(signal)}</Badge>
                            )) : "—"}
                          </div>
                        </TableCell>
                        <TableCell className="max-w-40 whitespace-normal text-muted-foreground">{recentTrigger(lead.triggered_at, lead.trigger) ?? "—"}</TableCell>
                        <TableCell><Badge variant="outline" className="capitalize">{lead.status}</Badge></TableCell>
                      </TableRow>
                    )
                  })}
                  {page.items.length === 0 && (
                    <TableRow><TableCell colSpan={7} className="py-10 text-center text-muted-foreground">No leads match these filters.</TableCell></TableRow>
                  )}
                </TableBody>
              </Table>
              <p className="mt-4 text-xs text-muted-foreground">
                Battery values estimate annual energy trading on ERCOT day-ahead plans, after efficiency losses, wear and a 20% backup reserve. They exclude retail margin, fees and ancillary services.
              </p>
              <div className="mt-4 flex items-center justify-between gap-3">
                <span className="text-sm text-muted-foreground">50 leads per page</span>
                <div className="flex gap-2">
                  {offset > 0 ? (
                    <Link href={pageHref(offset - PAGE_SIZE)} className={buttonVariants({ variant: "outline", size: "sm" })}>Previous</Link>
                  ) : <span className={buttonVariants({ variant: "outline", size: "sm", className: "pointer-events-none opacity-50" })}>Previous</span>}
                  {offset + PAGE_SIZE < page.total ? (
                    <Link href={pageHref(offset + PAGE_SIZE)} className={buttonVariants({ variant: "outline", size: "sm" })}>Next</Link>
                  ) : <span className={buttonVariants({ variant: "outline", size: "sm", className: "pointer-events-none opacity-50" })}>Next</span>}
                </div>
              </div>
            </CardContent>
          </Card>}
        </>
      )}
    </div>
  )
}
