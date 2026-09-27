"use client"

import Link from "next/link"
import { ExternalLinkIcon, HistoryIcon, MapPinIcon } from "lucide-react"

import { Disclosure } from "@/components/disclosure"
import { LeadLocationMap } from "@/components/leads/lead-location-map"
import { PriorityHelp } from "@/components/leads/priority-help"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import type { ZoneDetail } from "@/lib/grid"
import { BATTERY_SIZES, formatLeadMoney, signalLabel, valueBasis, type LeadDetail } from "@/lib/leads"
import { cn } from "@/lib/utils"

// Everything the lead drawer shows about the home itself (the former full lead page).

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

export function countyName(lead: LeadDetail): string {
  const c = lead.county
  return `${c.charAt(0).toUpperCase()}${c.slice(1)}${c.toLowerCase().endsWith(" county") ? "" : " County"}`
}

/** The home at a glance: where it is, what the latest signal says, and a small map. */
export function AddressCard({ lead }: { lead: LeadDetail }) {
  return (
    <div className="flex flex-col overflow-hidden rounded-xl border bg-card shadow-sm">
      {lead.lat !== null && lead.lon !== null && (
        <LeadLocationMap lat={lead.lat} lon={lead.lon} className="h-36 rounded-none border-0 border-b" />
      )}
      <div className="flex flex-col gap-2 p-3">
        <div className="flex items-start gap-2">
          <MapPinIcon className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
          <div className="min-w-0">
            <p className="text-base leading-tight font-semibold">{lead.address ?? "Address unavailable"}</p>
            <p className="text-xs text-muted-foreground">
              {[lead.city, lead.zip, countyName(lead)].filter(Boolean).join(" · ")}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          {lead.trigger && <Badge variant="secondary">Latest signal: {signalLabel(lead.trigger)}</Badge>}
          {lead.trigger && lead.triggered_at && <span className="text-muted-foreground">detected {formatDate(lead.triggered_at)}</span>}
          {lead.load_zone && <Badge variant="outline" className="font-mono">{lead.load_zone}</Badge>}
        </div>
        {lead.reasons && <p className="text-xs text-muted-foreground">{lead.reasons}</p>}
        {lead.lat !== null && lead.lon !== null && (
          <a
            href={`https://www.google.com/maps/search/?api=1&query=${lead.lat},${lead.lon}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex w-fit items-center gap-1 text-xs font-medium text-primary hover:underline"
          >
            Open in Google Maps <ExternalLinkIcon className="size-3" />
          </a>
        )}
      </div>
    </div>
  )
}

/** Priority value, the suggested battery and the 25/40/50 kWh options with their history. */
export function ValueSection({ lead, zone }: { lead: LeadDetail; zone: ZoneDetail | null }) {
  const batteryYears = [...(zone?.series.battery_years ?? [])].sort((a, b) => b.year - a.year)
  const suggestedValue = lead.recommended_kwh === null ? null : lead.battery_values?.[lead.recommended_kwh]
  const basisValue = suggestedValue ?? Object.values(lead.battery_values ?? {})[0]
  return (
    <div className="flex flex-col gap-3 px-3 text-sm">
      <p className="font-medium">
        {lead.recommended_kwh === null ? "Suggested size unavailable" : `Suggested size: ${lead.recommended_kwh} kWh`}
      </p>
      {lead.sizing_reason && <p className="text-xs text-muted-foreground">{lead.sizing_reason}</p>}
      <PriorityHelp />
      <div className="grid grid-cols-3 gap-2">
        {BATTERY_SIZES.map((size) => (
          <div key={size} className={cn("flex min-w-0 flex-col gap-1 rounded-lg border p-2", lead.recommended_kwh === size ? "border-primary bg-primary/5" : "border-border")}>
            <span className="text-xs font-medium">{size} kWh</span>
            <p className="font-semibold tabular-nums">
              {lead.battery_values === null ? "—" : <>{formatLeadMoney(lead.battery_values[size].value)}<span className="text-xs font-normal text-muted-foreground">/yr</span></>}
            </p>
            <p className="text-[11px] text-muted-foreground">{valueBasis(lead.battery_values?.[size])}</p>
            {lead.recommended_kwh === size && <Badge variant="secondary" className="w-fit">Suggested</Badge>}
          </div>
        ))}
      </div>
      <Disclosure title="Past years and how this is estimated" icon={HistoryIcon} className="text-xs text-muted-foreground">
        {BATTERY_SIZES.map((size) => {
          const v = lead.battery_values?.[size]
          return (
            <div key={size} className="flex flex-col gap-1">
              <p className="font-medium text-foreground">{size} kWh{size === lead.recommended_kwh && " · Suggested size"}</p>
              <p>{v && v.low !== null && v.low_year !== null && v.high !== null && v.high_year !== null
                ? `Full calendar years · Lowest: ${formatLeadMoney(v.low)} (${v.low_year}); highest: ${formatLeadMoney(v.high)} (${v.high_year}).`
                : "Full-year history unavailable."}</p>
              <p>Last 12 months: {v ? `${formatLeadMoney(v.recent)}/yr.` : "Unavailable."}</p>
              <p>Perfect-hindsight ceiling · {v && v.first_year !== null && v.last_year !== null ? "Average year" : valueBasis(v)}: {v ? `${formatLeadMoney(v.ceiling)}/yr.` : "Unavailable."}</p>
            </div>
          )
        })}
        <p>The perfect-hindsight ceiling is a benchmark assuming every future price was known.</p>
        {suggestedValue && suggestedValue.low !== null && suggestedValue.recent < suggestedValue.low && (
          <p>The last 12 months were below every full calendar year shown.</p>
        )}
        {batteryYears.length > 0 && (
          <Table aria-label="Historical grid value to Base by full calendar year, dollars per year">
            <TableHeader><TableRow>
              <TableHead scope="col">Year</TableHead>
              {BATTERY_SIZES.map((size) => (
                <TableHead key={size} scope="col" className={cn("text-right", size === lead.recommended_kwh && "bg-muted font-semibold")}>{size} kWh</TableHead>
              ))}
            </TableRow></TableHeader>
            <TableBody>
              {batteryYears.map((year) => (
                <TableRow key={year.year}>
                  <TableCell>{year.year}</TableCell>
                  {BATTERY_SIZES.map((size) => (
                    <TableCell key={size} className={cn("text-right tabular-nums", size === lead.recommended_kwh && "bg-muted font-semibold")}>
                      {formatLeadMoney(year[String(size) as "25" | "40" | "50"])}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
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
      {lead.value !== null && (
        <p className="text-xs text-muted-foreground">
          Historical grid value to Base: {formatLeadMoney(lead.value)}/yr · {valueBasis(basisValue).toLowerCase()}, based on this Load Zone.
        </p>
      )}
      {lead.load_zone && (
        <Link href={`/grid/${encodeURIComponent(lead.load_zone)}`} className="text-xs font-medium text-primary hover:underline">
          Why this zone? <span className="text-muted-foreground">{lead.load_zone}</span>
        </Link>
      )}
    </div>
  )
}

/** Appraisal facts, percentile drivers and recorded features. */
export function HomeProfile({ lead }: { lead: LeadDetail }) {
  const county = countyName(lead)
  const flagDrivers = lead.drivers.filter((d) => d.kind === "flag")
  const percentileDrivers = lead.drivers.filter((d) => d.kind === "percentile")
  const facts = [
    ["Heated area", lead.heated_sqft === null ? "—" : `${formatNumber(lead.heated_sqft)} sqft`],
    ["Market value", lead.market_value === null ? "—" : formatLeadMoney(lead.market_value)],
    ["Year built", lead.year_built?.toString() ?? "—"],
    ["Bedrooms", lead.bedrooms?.toString() ?? "—"],
    ["Baths", lead.full_baths === null && lead.half_baths === null ? "—" : `${lead.full_baths ?? "—"} full · ${lead.half_baths ?? "—"} half`],
    ["Stories", lead.stories?.toString() ?? "—"],
  ]
  return (
    <div className="flex flex-col gap-3 px-3 text-sm">
      <dl className="grid grid-cols-3 gap-3">
        {facts.map(([label, value]) => (
          <div key={label}>
            <dt className="text-[11px] text-muted-foreground">{label}</dt>
            <dd className="font-medium tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
      {percentileDrivers.length > 0 && (
        <>
          <Separator />
          <div className="flex flex-col gap-1 text-xs">
            {percentileDrivers.map((d) => (
              <p key={d.key}>
                {d.value === null
                  ? `${d.label}: unavailable`
                  : `Top ${topPercent(d.score)}% by ${d.key === "home_size" ? "size" : "value"} among eligible homes in ${county}`}
              </p>
            ))}
          </div>
        </>
      )}
      {flagDrivers.length > 0 && (
        <>
          <Separator />
          <div className="flex flex-wrap gap-1.5">
            {flagDrivers.map((d) => (
              <Badge key={d.key} variant={d.value === true ? "secondary" : "outline"}>
                {signalLabel(d.key)}: {d.value === true ? "Yes" : "No"}
              </Badge>
            ))}
          </div>
          <p className="text-[11px] text-muted-foreground">No = not found in available records.</p>
        </>
      )}
      <Separator />
      <div className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
        <p>{county} · Appraisal account {lead.account}</p>
        <p>First seen {formatDateTime(lead.first_seen_at)} · Scored {formatDateTime(lead.scored_at)}</p>
      </div>
    </div>
  )
}

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

/** Prompts to confirm the available records with the homeowner. */
export function talkingPoints(lead: LeadDetail): string[] {
  const has = (key: string) => lead.drivers.some((d) => d.kind === "flag" && d.key === key && d.value === true)
  const ownerEvidence = lead.evidence.find((item) => item.type === "new_owner" && item.date)
  const points: string[] = []
  if (has("solar")) points.push(signalTalkingPoint(lead.evidence, "solar",
    "ask about backup power needs and battery pairing.",
    "confirm whether a system is installed and ask about backup power needs and battery pairing."))
  if (has("pool")) points.push("Pool or spa recorded — ask about equipment, usage, and backup priorities.")
  if (has("ev_charger")) points.push(signalTalkingPoint(lead.evidence, "ev_charger",
    "ask about charging times and backup priorities.",
    "confirm whether a charger is installed and ask about charging times."))
  if (has("new_owner")) points.push(ownerEvidence?.date
    ? `Owner-change signal dated ${formatEvidenceDate(ownerEvidence.date)} — ask about move-in timing.`
    : "Owner-change signal — ask about move-in timing.")
  if (has("new_home")) points.push(signalTalkingPoint(lead.evidence, "new_home",
    "ask about backup power needs and installation planning.",
    "confirm the home's construction and occupancy status before discussing installation."))
  if (lead.signals.includes("new_meter")) points.push("New-meter signal — ask about the service change and current power needs.")
  return points
}

export function TalkingPoints({ points }: { points: string[] }) {
  return (
    <div className="px-3 text-sm">
      {points.length ? (
        <ul className="flex list-disc flex-col gap-2 pl-5">
          {points.map((p) => <li key={p}>{p}</li>)}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground">Review the home profile and source evidence before outreach.</p>
      )}
    </div>
  )
}

export function EvidenceList({ lead }: { lead: LeadDetail }) {
  return (
    <div className="px-3">
      {lead.evidence.length ? (
        <ul className="divide-y divide-border">
          {lead.evidence.map((item, index) => (
            <li key={`${item.type}-${item.date}-${index}`} className="flex flex-col gap-1 py-2 first:pt-0 last:pb-0">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary">{signalLabel(item.type)}</Badge>
                <span className="text-xs text-muted-foreground">{formatEvidenceDate(item.date)}</span>
              </div>
              <p className="text-sm">{item.detail}</p>
              <p className="text-xs text-muted-foreground">Source: {item.source.replaceAll("_", " ")}</p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground">No signal evidence yet.</p>
      )}
    </div>
  )
}
