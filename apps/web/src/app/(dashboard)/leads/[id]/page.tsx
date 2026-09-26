import Link from "next/link"
import { notFound } from "next/navigation"
import { connection } from "next/server"
import { ArrowLeftIcon } from "lucide-react"

import { StatusControl } from "@/components/leads/status-control"
import { LeadLocationMap } from "@/components/leads/lead-location-map"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { apiFetch } from "@/lib/api"
import { scoreColor } from "@/lib/grid"
import { formatLeadDriverValue, signalLabel, type LeadDetail } from "@/lib/leads"

const formatNumber = (value: number | null) =>
  value === null ? "—" : Math.round(value).toLocaleString("en-US")

const formatDateTime = (value: string) =>
  new Date(value).toLocaleString("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "America/Chicago",
  })

const formatEvidenceDate = (value: string | null) =>
  value
    ? new Date(`${value}T00:00:00Z`).toLocaleDateString("en-US", {
        dateStyle: "medium",
        timeZone: "UTC",
      })
    : "Date unavailable"

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

  const facts = [
    ["County", lead.county],
    ["Account", lead.account],
    ["Market value", lead.market_value === null ? "—" : `$${formatNumber(lead.market_value)}`],
    ["Heated area", lead.heated_sqft === null ? "—" : `${formatNumber(lead.heated_sqft)} sqft`],
    ["Year built", lead.year_built?.toString() ?? "—"],
    ["First seen", formatDateTime(lead.first_seen_at)],
    ["Scored at", formatDateTime(lead.scored_at)],
  ]

  return (
    <div className="flex flex-col gap-6 px-4 py-4 md:py-6 lg:px-6">
      <Link
        href="/leads"
        className="flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeftIcon className="size-4" /> All leads
      </Link>

      <div className="flex items-start gap-4">
        <div
          className="flex size-20 shrink-0 flex-col items-center justify-center rounded-xl"
          style={{ background: scoreColor(lead.score) }}
        >
          <span className="text-3xl font-semibold tabular-nums">{lead.score.toFixed(0)}</span>
          <span className="text-[10px] uppercase tracking-wide">Lead score</span>
        </div>
        <div className="flex flex-col gap-2">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              {lead.address ?? "Address unavailable"}
            </h1>
            <p className="text-sm text-muted-foreground">
              {[lead.city, lead.zip].filter(Boolean).join(" · ")}
            </p>
          </div>
          <p className="text-sm">{lead.reasons}</p>
          <div className="flex flex-wrap gap-2">
            {lead.trigger && <Badge variant="secondary">Trigger: {signalLabel(lead.trigger)}</Badge>}
            <Badge variant="outline">Status: {lead.status}</Badge>
            {lead.signals.map((signal) => (
              <Badge key={signal} variant="outline">{signalLabel(signal)}</Badge>
            ))}
          </div>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-5">
        <div className="flex flex-col gap-4 xl:col-span-3">
          <div>
            <h2 className="text-lg font-semibold">Score drivers</h2>
            <p className="text-sm text-muted-foreground">How this property earned its lead score.</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {lead.drivers.map((driver) => (
              <Card key={driver.key} size="sm">
                <CardHeader>
                  <CardTitle className="flex items-baseline justify-between gap-2">
                    <span>{driver.label}</span>
                    <span className="text-base tabular-nums">{formatLeadDriverValue(driver)}</span>
                  </CardTitle>
                  <CardDescription className="text-xs">
                    Score {driver.score.toFixed(0)}/100 · {Math.round(driver.weight * 100)}% of lead score
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <Progress value={driver.score} aria-label={`${driver.label} score`} />
                </CardContent>
              </Card>
            ))}
          </div>
          <Card size="sm">
            <CardHeader><CardTitle>Evidence</CardTitle></CardHeader>
            <CardContent>
              {lead.evidence.length ? (
                <ul className="divide-y divide-border">
                  {lead.evidence.map((item, index) => (
                    <li key={`${item.type}-${item.date}-${index}`} className="flex flex-col gap-1 py-3 first:pt-0 last:pb-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="secondary">{signalLabel(item.type)}</Badge>
                        <span className="text-xs text-muted-foreground">{formatEvidenceDate(item.date)}</span>
                      </div>
                      <p className="text-sm">{item.detail}</p>
                      <p className="text-xs text-muted-foreground">Source: {item.source}</p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">No signal evidence yet.</p>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="flex flex-col gap-4 xl:col-span-2">
          <Card size="sm">
            <CardHeader><CardTitle>Review</CardTitle></CardHeader>
            <CardContent><StatusControl id={lead.id} status={lead.status} /></CardContent>
          </Card>
          <Card size="sm">
            <CardHeader><CardTitle>Property facts</CardTitle></CardHeader>
            <CardContent>
              <dl className="grid gap-3 text-sm">
                {facts.map(([label, value]) => (
                  <div key={label} className="flex justify-between gap-4">
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className="text-right tabular-nums">{value}</dd>
                  </div>
                ))}
              </dl>
            </CardContent>
          </Card>
          {lead.lat !== null && lead.lon !== null && (
            <Card size="sm">
              <CardHeader><CardTitle>Location</CardTitle></CardHeader>
              <CardContent><LeadLocationMap lat={lead.lat} lon={lead.lon} score={lead.score} /></CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
