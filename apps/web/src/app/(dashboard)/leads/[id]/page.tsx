import type { Metadata } from "next"
import Link from "next/link"
import { notFound } from "next/navigation"
import { connection } from "next/server"
import { ExternalLinkIcon, HistoryIcon } from "lucide-react"

import { Disclosure } from "@/components/disclosure"
import { ConsumptionCard } from "@/components/leads/consumption-card"
import { LeadLocationMap } from "@/components/leads/lead-location-map"
import { PriorityHelp } from "@/components/leads/priority-help"
import { StatusControl } from "@/components/leads/status-control"
import { SiteHeader } from "@/components/site-header"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiFetch } from "@/lib/api"
import type { ZoneDetail } from "@/lib/grid"
import { BATTERY_SIZES, STATUS_LABELS, formatLeadMoney, leadReturnHref, signalLabel, valueBasis, type LeadDetail } from "@/lib/leads"
import { cn } from "@/lib/utils"

const formatNumber = (value: number | null) => value === null ? "—" : Math.round(value).toLocaleString("en-US")
const formatDateTime = (value: string) => new Date(value).toLocaleString("en-US", {
  dateStyle: "medium", timeStyle: "short", timeZone: "America/Chicago",
})
const formatDate = (value: string) => new Date(value).toLocaleDateString("en-US", {
  dateStyle: "medium", timeZone: "America/Chicago",
})
const formatEvidenceDate = (value: string | null) => value
  ? new Date(`${value}T00:00:00Z`).toLocaleDateString("en-US", { dateStyle: "medium", timeZone: "UTC" })
  : "Date unavailable"
const topPercent = (score: number) => Math.round(100 - score)

function signalTalkingPoint(evidence: LeadDetail["evidence"], signal: string, prompt: string, confirmation: string): string {
  const records = evidence.filter((item) => item.type === signal)
  const permit = records.filter((item) => item.source.includes("permit"))
    .sort((a, b) => (b.date ?? "").localeCompare(a.date ?? ""))[0]
  const sources: string[] = []
  if (permit) {
    const date = permit.date ? new Date(`${permit.date}T00:00:00Z`).toLocaleDateString("en-US", {
      month: "short", year: "numeric", timeZone: "UTC",
    }) : "date unavailable"
    sources.push(`permit ${date}`)
  }
  if (records.some((item) => item.source === "appraisal")) sources.push("appraisal")
  const appraisalOnly = records.length > 0 && records.every((item) => item.source === "appraisal" && item.date === null)
  return `${signalLabel(signal)} ${records.length ? "on record" : "signal"}${sources.length ? ` (${sources.join(" + ")})` : ""} — ${appraisalOnly ? confirmation : prompt}`
}

async function getLead(rawId: string) {
  const id = Number(rawId)
  if (!Number.isSafeInteger(id) || id <= 0) notFound()

  try {
    return await apiFetch<LeadDetail>(`/leads/${id}`, { cache: "no-store" })
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("API 404 ")) notFound()
    throw error
  }
}

export async function generateMetadata(props: PageProps<"/leads/[id]">): Promise<Metadata> {
  const { id } = await props.params
  const lead = await getLead(id)
  return { title: lead.address ?? "Lead details" }
}

export default async function LeadDetailPage(props: PageProps<"/leads/[id]">) {
  await connection()
  const { id } = await props.params
  const leadPromise = getLead(id)
  // The lead supplies the Load Zone, so start its history fetch as soon as it resolves.
  const zonePromise = leadPromise.then((lead) => lead.load_zone
    ? apiFetch<ZoneDetail>(`/grid/zones/${encodeURIComponent(lead.load_zone)}`, { cache: "no-store" }).catch(() => null)
    : null)
  const [lead, zone, { back }] = await Promise.all([leadPromise, zonePromise, props.searchParams])
  const returnHref = leadReturnHref(back)
  const batteryYears = [...(zone?.series.battery_years ?? [])].sort((a, b) => b.year - a.year)
  const suggestedValue = lead.recommended_kwh === null ? null : lead.battery_values?.[lead.recommended_kwh]
  const basisValue = suggestedValue ?? Object.values(lead.battery_values ?? {})[0]

  const flagDrivers = lead.drivers.filter((driver) => driver.kind === "flag")
  const percentileDrivers = lead.drivers.filter((driver) => driver.kind === "percentile")
  const hasFlag = (key: string) => flagDrivers.some((driver) => driver.key === key && driver.value === true)
  const ownerEvidence = lead.evidence.find((item) => item.type === "new_owner" && item.date)
  const countyName = `${lead.county.charAt(0).toUpperCase()}${lead.county.slice(1)}${lead.county.toLowerCase().endsWith(" county") ? "" : " County"}`
  const talkingPoints: string[] = []
  if (hasFlag("solar")) talkingPoints.push(signalTalkingPoint(lead.evidence, "solar",
    "ask about backup power needs and battery pairing.",
    "confirm whether a system is installed and ask about backup power needs and battery pairing."))
  if (hasFlag("pool")) talkingPoints.push("Pool or spa recorded — ask about equipment, usage, and backup priorities.")
  if (hasFlag("ev_charger")) talkingPoints.push(signalTalkingPoint(lead.evidence, "ev_charger",
    "ask about charging times and backup priorities.",
    "confirm whether a charger is installed and ask about charging times."))
  if (hasFlag("new_owner")) talkingPoints.push(ownerEvidence?.date
    ? `Owner-change signal dated ${formatEvidenceDate(ownerEvidence.date)} — ask about move-in timing.`
    : "Owner-change signal — ask about move-in timing.")
  if (hasFlag("new_home")) talkingPoints.push(signalTalkingPoint(lead.evidence, "new_home",
    "ask about backup power needs and installation planning.",
    "confirm the home's construction and occupancy status before discussing installation."))
  if (lead.signals.includes("new_meter")) talkingPoints.push("New-meter signal — ask about the service change and current power needs.")

  const facts = [
    ["Heated area", lead.heated_sqft === null ? "—" : `${formatNumber(lead.heated_sqft)} sqft`],
    ["Market value", lead.market_value === null ? "—" : formatLeadMoney(lead.market_value)],
    ["Year built", lead.year_built?.toString() ?? "—"],
    ["Bedrooms", lead.bedrooms?.toString() ?? "—"],
    ["Baths", lead.full_baths === null && lead.half_baths === null ? "—" : `${lead.full_baths ?? "—"} full · ${lead.half_baths ?? "—"} half`],
    ["Stories", lead.stories?.toString() ?? "—"],
  ]

  return (
    <>
      <SiteHeader title={lead.address ?? "Address unavailable"} parent={{ title: "Leads", href: returnHref }} />
      <div className="flex flex-col gap-6 px-4 py-4 md:py-6 lg:px-6">
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">{[lead.city, lead.zip].filter(Boolean).join(" · ")}</p>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">{STATUS_LABELS[lead.status]}</Badge>
            {lead.trigger && <Badge variant="secondary">
              Latest signal: {signalLabel(lead.trigger)}
            </Badge>}
            {lead.trigger && lead.triggered_at && <span className="text-xs text-muted-foreground">Detected {formatDate(lead.triggered_at)}</span>}
          </div>
          <p className="max-w-2xl text-sm text-muted-foreground">{lead.reasons}</p>
        </div>
        <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]">
          <Card>
            <CardHeader>
              <CardTitle>Priority value</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-3">
                <p className="text-3xl font-semibold tabular-nums">
                  {lead.expected_value === null ? "Value unavailable" : `${formatLeadMoney(lead.expected_value)}/yr`}
                </p>
              </div>
              <PriorityHelp />
              <p className="font-medium">{lead.recommended_kwh === null
                ? "Suggested size unavailable"
                : `Suggested size: ${lead.recommended_kwh} kWh`}</p>
              {lead.sizing_reason && <p className="text-sm text-muted-foreground">{lead.sizing_reason}</p>}
              {lead.value !== null && <p className="text-xs text-muted-foreground">Historical grid value to Base: {formatLeadMoney(lead.value)}/yr · {valueBasis(basisValue).toLowerCase()}, based on this Load Zone.</p>}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Review lead</CardTitle>
              <CardDescription>Record your review progress.</CardDescription>
            </CardHeader>
            <CardContent><StatusControl key={lead.id} id={lead.id} status={lead.status} /></CardContent>
          </Card>
        </div>

        <div className="grid gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(300px,2fr)]">
          <div className="flex flex-col gap-6">
            <Card>
              <CardHeader>
                <CardTitle>Battery options</CardTitle>
                <CardDescription>Historical grid value to Base, shared by homes in this Load Zone.</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                <div className="grid grid-cols-3 gap-2 sm:gap-3">
                  {BATTERY_SIZES.map((size) => (
                    <div key={size} className={cn("flex min-w-0 flex-col gap-3 rounded-lg border p-2 sm:p-4", lead.recommended_kwh === size ? "border-primary bg-primary/5" : "border-border")}>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{size} kWh</span>
                      </div>
                      <p className="text-sm font-semibold tabular-nums sm:text-xl">
                        {lead.battery_values === null ? <span aria-label="Value unavailable">—</span> : <>{formatLeadMoney(lead.battery_values[size].value)}<span className="text-xs font-normal text-muted-foreground">/yr</span></>}
                      </p>
                      <p className="text-xs text-muted-foreground">{valueBasis(lead.battery_values?.[size])}</p>
                      {lead.recommended_kwh === size && <Badge variant="secondary">Suggested</Badge>}
                    </div>
                  ))}
                </div>
                <Disclosure title="Past years and how this is estimated" icon={HistoryIcon} className="text-xs text-muted-foreground">
                    {BATTERY_SIZES.map((size) => {
                      const batteryValue = lead.battery_values?.[size]
                      return (
                        <div key={size} className="flex flex-col gap-1">
                          <p className="font-medium text-foreground">{size} kWh{size === lead.recommended_kwh && " · Suggested size"}</p>
                          <p>{batteryValue && batteryValue.low !== null && batteryValue.low_year !== null && batteryValue.high !== null && batteryValue.high_year !== null
                            ? `Full calendar years · Lowest: ${formatLeadMoney(batteryValue.low)} (${batteryValue.low_year}); highest: ${formatLeadMoney(batteryValue.high)} (${batteryValue.high_year}).`
                            : "Full-year history unavailable."}</p>
                          <p>Last 12 months: {batteryValue ? `${formatLeadMoney(batteryValue.recent)}/yr.` : "Unavailable."}</p>
                          <p>Perfect-hindsight ceiling · {batteryValue && batteryValue.first_year !== null && batteryValue.last_year !== null ? "Average year" : valueBasis(batteryValue)}: {batteryValue ? `${formatLeadMoney(batteryValue.ceiling)}/yr.` : "Unavailable."}</p>
                        </div>
                      )
                    })}
                    <p>The perfect-hindsight ceiling is a benchmark assuming every future price was known.</p>
                    {suggestedValue && suggestedValue.low !== null && suggestedValue.recent < suggestedValue.low && <p>
                      The last 12 months were below every full calendar year shown.
                    </p>}
                    {batteryYears.length > 0 && <Table aria-label="Historical grid value to Base by full calendar year, dollars per year">
                      <TableHeader><TableRow>
                        <TableHead scope="col">Year</TableHead>
                        {BATTERY_SIZES.map((size) => <TableHead key={size} scope="col" className={cn("text-right", size === lead.recommended_kwh && "bg-muted font-semibold")}>
                          {size} kWh{size === lead.recommended_kwh && <span className="sr-only"> · Suggested size</span>}
                        </TableHead>)}
                      </TableRow></TableHeader>
                      <TableBody>
                        {batteryYears.map((year) => <TableRow key={year.year}>
                          <TableCell>{year.year}</TableCell>
                          {BATTERY_SIZES.map((size) => <TableCell key={size} className={cn("text-right tabular-nums", size === lead.recommended_kwh && "bg-muted font-semibold")}>
                            {formatLeadMoney(year[String(size) as "25" | "40" | "50"])}
                          </TableCell>)}
                        </TableRow>)}
                      </TableBody>
                    </Table>}
                    <p>
                      {basisValue && basisValue.first_year !== null && basisValue.last_year !== null && <>
                        Average of full calendar years {basisValue.first_year}–{basisValue.last_year}, so one unusually
                        quiet or spiky year doesn&apos;t drive the ranking.{" "}
                      </>}
                      Simulated energy-trading value using ERCOT day-ahead plans and real-time prices, without hindsight.
                      Includes energy losses, 2¢/kWh battery wear and 20% kept for backup. Excludes retail margin, fees
                      and ancillary services. Historical estimate, not forecast revenue or customer savings.
                    </p>
                </Disclosure>
                {lead.load_zone && <Link href={`/grid/${encodeURIComponent(lead.load_zone)}`} className="text-sm font-medium text-primary hover:underline">
                  Why this zone? <span className="text-muted-foreground">{lead.load_zone}</span>
                </Link>}
              </CardContent>
            </Card>

            <ConsumptionCard lead={lead} />

            <Card>
              <CardHeader>
                <CardTitle>Talking points</CardTitle>
                <CardDescription>Prompts to confirm the available records with the homeowner.</CardDescription>
              </CardHeader>
              <CardContent>
                {talkingPoints.length ? <ul className="flex list-disc flex-col gap-2 pl-5 text-sm">
                  {talkingPoints.map((point) => <li key={point}>{point}</li>)}
                </ul> : <p className="text-sm text-muted-foreground">Review the home profile and source evidence before outreach.</p>}
              </CardContent>
            </Card>
          </div>

          <div className="flex flex-col gap-6">
            <Card>
              <CardHeader><CardTitle>Home profile</CardTitle></CardHeader>
              <CardContent className="flex flex-col gap-4">
                <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-3">
                  {facts.map(([label, value]) => <div key={label}>
                    <dt className="text-xs text-muted-foreground">{label}</dt>
                    <dd className="mt-1 font-medium tabular-nums">{value}</dd>
                  </div>)}
                </dl>
                <Separator />
                <div className="flex flex-col gap-1 text-xs text-muted-foreground">
                  <p>{countyName} · Appraisal account {lead.account}</p>
                  <p>First seen {formatDateTime(lead.first_seen_at)} · Scored {formatDateTime(lead.scored_at)}</p>
                </div>
                {percentileDrivers.length > 0 && <><Separator /><div className="flex flex-col gap-1 text-sm">
                  {percentileDrivers.map((driver) => <p key={driver.key}>
                    {driver.value === null
                      ? `${driver.label}: unavailable`
                      : `Top ${topPercent(driver.score)}% by ${driver.key === "home_size" ? "size" : "value"} among eligible homes in ${countyName}`}
                  </p>)}
                </div></>}
                {flagDrivers.length > 0 && <><Separator /><div className="flex flex-col gap-2">
                  <div className="flex flex-wrap gap-2">
                    {flagDrivers.map((driver) => <Badge key={driver.key} variant={driver.value === true ? "secondary" : "outline"}>
                      {signalLabel(driver.key)} recorded: {driver.value === true ? "Yes" : "No"}
                    </Badge>)}
                  </div>
                  <p className="text-xs text-muted-foreground">No = not found in available records.</p>
                </div></>}
              </CardContent>
            </Card>
            {lead.lat !== null && lead.lon !== null && <Card>
              <CardHeader><CardTitle>Location</CardTitle></CardHeader>
              <CardContent className="flex flex-col gap-3">
                <LeadLocationMap lat={lead.lat} lon={lead.lon} score={lead.score} />
                <a href={`https://www.google.com/maps/search/?api=1&query=${lead.lat},${lead.lon}`}
                  target="_blank" rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline">
                  Open in Google Maps <ExternalLinkIcon className="size-3.5" />
                </a>
              </CardContent>
            </Card>}
          </div>
        </div>


        <Card size="sm">
          <CardHeader><CardTitle>Evidence &amp; sources</CardTitle></CardHeader>
          <CardContent>
            {lead.evidence.length ? <ul className="divide-y divide-border">
              {lead.evidence.map((item, index) => <li key={`${item.type}-${item.date}-${index}`} className="flex flex-col gap-1 py-3 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="secondary">{signalLabel(item.type)}</Badge>
                  <span className="text-xs text-muted-foreground">{formatEvidenceDate(item.date)}</span>
                </div>
                <p className="text-sm">{item.detail}</p>
                <p className="text-xs text-muted-foreground">Source: {item.source.replaceAll("_", " ")}</p>
              </li>)}
            </ul> : <p className="text-sm text-muted-foreground">No signal evidence yet.</p>}
          </CardContent>
        </Card>
      </div>
    </>
  )
}
