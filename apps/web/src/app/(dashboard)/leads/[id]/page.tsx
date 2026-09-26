import Link from "next/link"
import { notFound } from "next/navigation"
import { connection } from "next/server"
import { ArrowLeftIcon, ExternalLinkIcon } from "lucide-react"

import { LeadLocationMap } from "@/components/leads/lead-location-map"
import { StatusControl } from "@/components/leads/status-control"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiFetch } from "@/lib/api"
import { formatLeadDriverValue, signalLabel, type LeadDetail } from "@/lib/leads"
import { cn } from "@/lib/utils"

const BATTERY_SIZES = [25, 40, 50] as const
const formatNumber = (value: number | null) => value === null ? "—" : Math.round(value).toLocaleString("en-US")
const formatMoney = (value: number) => `$${formatNumber(value)}`
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

export default async function LeadDetailPage(props: PageProps<"/leads/[id]">) {
  await connection()
  const { id: rawId } = await props.params
  const id = Number(rawId)
  if (!Number.isSafeInteger(id) || id <= 0) notFound()

  let lead: LeadDetail
  try {
    lead = await apiFetch<LeadDetail>(`/leads/${id}`, { cache: "no-store" })
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("API 404 ")) notFound()
    throw error
  }

  const flagDrivers = lead.drivers.filter((driver) => driver.kind === "flag")
  const percentileDrivers = lead.drivers.filter((driver) => driver.kind === "percentile")
  const hasFlag = (key: string) => flagDrivers.some((driver) => driver.key === key && driver.value === true)
  const homeSize = percentileDrivers.find((driver) => driver.key === "home_size")
  const homeValue = percentileDrivers.find((driver) => driver.key === "home_value")
  const ownerEvidence = lead.evidence.find((item) => item.type === "new_owner" && item.date)
  const countyName = `${lead.county.charAt(0).toUpperCase()}${lead.county.slice(1)}${lead.county.toLowerCase().endsWith(" county") ? "" : " County"}`
  const talkingPoints: string[] = []
  if (hasFlag("solar")) talkingPoints.push("Already has solar: a battery stores daytime surplus for the evening peak and outages.")
  if (hasFlag("pool")) talkingPoints.push("Pool or spa: high year-round usage means a bigger bill to protect.")
  if (hasFlag("ev_charger")) talkingPoints.push("EV charger: a large evening load makes storage worth discussing.")
  if (hasFlag("new_owner")) talkingPoints.push(ownerEvidence?.date
    ? `New owner since ${formatEvidenceDate(ownerEvidence.date)}: setting up utilities now.`
    : "New owner: a good time to discuss power needs while settling in.")
  if (hasFlag("new_home")) {
    const recentBuild = lead.year_built !== null && lead.year_built >= new Date(lead.scored_at).getFullYear() - 5
    talkingPoints.push(recentBuild
      ? `New build (${lead.year_built}): a battery can be planned with fewer retrofit constraints.`
      : "New-home signal: ask about backup power while the home's energy setup is still taking shape.")
  }
  if (homeSize && homeSize.value !== null && homeSize.score >= 80) {
    talkingPoints.push(`Top ${topPercent(homeSize.score)}% by size among eligible homes in ${countyName}.`)
  }
  if (homeValue && homeValue.value !== null && homeValue.score >= 80) {
    talkingPoints.push(`Top ${topPercent(homeValue.score)}% by value among eligible homes in ${countyName}.`)
  }

  const facts = [
    ["Heated area", lead.heated_sqft === null ? "—" : `${formatNumber(lead.heated_sqft)} sqft`],
    ["Market value", lead.market_value === null ? "—" : formatMoney(lead.market_value)],
    ["Year built", lead.year_built?.toString() ?? "—"],
  ]

  return (
    <div className="flex flex-col gap-6 px-4 py-4 md:py-6 lg:px-6">
      <Link href="/leads" className="flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeftIcon className="size-4" /> All leads
      </Link>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]">
        <div className="flex flex-col gap-3">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">{lead.address ?? "Address unavailable"}</h1>
            <p className="text-sm text-muted-foreground">{[lead.city, lead.zip].filter(Boolean).join(" · ")}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline" className="capitalize">{lead.status}</Badge>
            {lead.trigger && <Badge variant="secondary">
              Why now: {signalLabel(lead.trigger)}{lead.triggered_at ? ` · ${formatDate(lead.triggered_at)}` : ""}
            </Badge>}
          </div>
          <p className="max-w-2xl text-sm text-muted-foreground">{lead.reasons}</p>
        </div>
        <Card>
          <CardHeader>
            <CardDescription>Expected value</CardDescription>
            <CardTitle className="text-3xl font-semibold tabular-nums">
              {lead.expected_value === null ? "Value unavailable" : `${formatMoney(lead.expected_value)}/yr`}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <Badge variant="secondary" className="tabular-nums">Fit {lead.score.toFixed(0)}/100</Badge>
            <p className="font-medium">{lead.recommended_kwh === null
              ? "Battery recommendation unavailable"
              : `Pitch a ${lead.recommended_kwh} kWh Base battery`}</p>
            {lead.sizing_reason && <p className="text-sm text-muted-foreground">{lead.sizing_reason}</p>}
            {lead.value !== null && <p className="text-xs text-muted-foreground">Battery grid value: {formatMoney(lead.value)}/yr</p>}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(300px,2fr)]">
        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Battery options</CardTitle>
              <CardDescription>Estimated annual grid value at this home.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="grid gap-3 sm:grid-cols-3">
                {BATTERY_SIZES.map((size) => (
                  <div key={size} className={cn("rounded-lg border p-4", lead.recommended_kwh === size ? "border-primary bg-primary/5" : "border-border")}>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{size} kWh</span>
                      {lead.recommended_kwh === size && <Badge>Pitch</Badge>}
                    </div>
                    <p className="mt-3 text-xl font-semibold tabular-nums">
                      {lead.battery_values === null ? "Value unavailable" : `${formatMoney(lead.battery_values[size])}/yr`}
                    </p>
                  </div>
                ))}
              </div>
              <p className="text-xs leading-relaxed text-muted-foreground">
                Battery values are a historical screening estimate of energy-arbitrage value from ERCOT real-time prices (perfect hindsight, last 12 months); they exclude retail margin, fees and ancillary services.
              </p>
              {lead.load_zone && <Link href={`/grid/${encodeURIComponent(lead.load_zone)}`} className="text-sm font-medium text-primary hover:underline">
                Why this zone? <span className="text-muted-foreground">{lead.load_zone}</span>
              </Link>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Talking points</CardTitle>
              <CardDescription>What makes this home worth a conversation.</CardDescription>
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
            <CardHeader><CardTitle>Next step</CardTitle></CardHeader>
            <CardContent><StatusControl id={lead.id} status={lead.status} /></CardContent>
          </Card>
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
                    : `Top ${topPercent(driver.score)}% by ${driver.key === "home_size" ? "size" : "value"} among eligible homes`}
                </p>)}
              </div></>}
              {flagDrivers.length > 0 && <><Separator /><div className="flex flex-wrap gap-2">
                {flagDrivers.map((driver) => <Badge key={driver.key} variant={driver.value === true ? "secondary" : "outline"}>
                  {driver.label}: {driver.value === true ? "Yes" : "No"}
                </Badge>)}
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
        <details>
          <summary className="cursor-pointer px-3 font-medium">Score breakdown <span className="ml-2 text-xs font-normal text-muted-foreground">How fit is calculated</span></summary>
          <CardContent className="mt-3 flex flex-col gap-3">
            <p className="text-xs text-muted-foreground">Each driver contributes its score (0–100) multiplied by its weight.</p>
            <Table>
              <TableHeader><TableRow>
                <TableHead>Driver</TableHead>
                <TableHead className="text-right">Weight</TableHead>
                <TableHead className="text-right">Points</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {lead.drivers.map((driver) => <TableRow key={driver.key}>
                  <TableCell><span className="font-medium">{driver.label}</span><span className="block text-xs text-muted-foreground">{formatLeadDriverValue(driver)}</span></TableCell>
                  <TableCell className="text-right tabular-nums">{Math.round(driver.weight * 100)}%</TableCell>
                  <TableCell className="text-right tabular-nums">{(driver.score * driver.weight).toFixed(1)}</TableCell>
                </TableRow>)}
                <TableRow>
                  <TableCell className="font-medium">Fit score</TableCell><TableCell />
                  <TableCell className="text-right font-medium tabular-nums">{lead.score.toFixed(1)}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </CardContent>
        </details>
      </Card>

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
  )
}
