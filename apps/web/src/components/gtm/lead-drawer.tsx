"use client"

import * as React from "react"
import Link from "next/link"

import { BaselineNeedBlock } from "@/components/need/baseline-need"
import { ForecastSignals } from "@/components/need/forecast-signals"
import { LiveGridSection } from "@/components/need/live-grid"
import { NwsAlerts } from "@/components/need/nws-alerts"
import { OutageBreakdown } from "@/components/need/outage-breakdown"
import { PropensityBlock } from "@/components/need/propensity"
import { Score } from "@/components/need/score-parts"
import { WeatherBreakdown } from "@/components/need/weather-breakdown"
import { ConsumptionCard } from "@/components/leads/consumption-card"
import { PanelCard, Tag } from "@/components/gtm/panel-card"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { apiFetch } from "@/lib/api"
import { formatLeadMoney, type LeadDetail } from "@/lib/leads"
import type { AlertFeed, CellDetail, ForecastFeed, LiveGrid } from "@/lib/need"

/** A lead and its Cell's "why", without leaving the map. */
export function LeadDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const [lead, setLead] = React.useState<LeadDetail | null>(null)
  const [cell, setCell] = React.useState<CellDetail | null>(null)
  const [error, setError] = React.useState<{ id: number; message: string } | null>(null)

  React.useEffect(() => {
    if (id === null) return
    const controller = new AbortController()
    apiFetch<LeadDetail>(`/leads/${id}`, { signal: controller.signal })
      .then((detail) => {
        setLead(detail)
        if (detail.h3_index) {
          return apiFetch<CellDetail>(`/need/cells/${detail.h3_index}`, { signal: controller.signal }).then(setCell)
        }
        setCell(null)
      })
      .catch((e: Error) => {
        if (!controller.signal.aborted) setError({ id, message: e.message })
      })
    return () => controller.abort()
  }, [id])

  const shown = lead?.id === id ? lead : null
  const shownCell = shown && cell?.h3 === shown.h3_index ? cell : null
  const failed = error?.id === id ? error.message : null

  return (
    <Sheet open={id !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{shown?.address ?? "Lead"}</SheetTitle>
          <SheetDescription>
            {shown ? `${shown.city ?? ""} ${shown.zip ?? ""} · ${shown.load_zone ?? "no load zone"}` : failed ? "Couldn't load this lead" : "Loading…"}
            {shown && (
              <>
                {" · "}
                <Link href={`/leads/${shown.id}`} className="underline">
                  open full page
                </Link>
              </>
            )}
          </SheetDescription>
        </SheetHeader>
        {failed && <p className="px-4 text-xs text-destructive">{failed}</p>}
        {shown && (
          <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pb-6">
            <PanelCard
              title="This home"
              value={shown.expected_value !== null ? <span className="font-semibold tabular-nums">{formatLeadMoney(shown.expected_value)}/yr</span> : "—"}
            >
              <div className="flex flex-col gap-2 px-3 text-sm">
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                  <dt className="text-muted-foreground">Expected Value</dt>
                  <dd className="text-right tabular-nums">{shown.expected_value !== null ? formatLeadMoney(shown.expected_value) : "—"}</dd>
                  <dt className="text-muted-foreground">Suggested battery</dt>
                  <dd className="text-right tabular-nums">{shown.recommended_kwh ? `${shown.recommended_kwh} kWh` : "—"}</dd>
                  <dt className="text-muted-foreground">Home</dt>
                  <dd className="text-right tabular-nums">
                    {shown.heated_sqft ? `${Math.round(shown.heated_sqft).toLocaleString("en-US")} sqft` : "—"}
                    {shown.year_built ? ` · ${shown.year_built}` : ""}
                  </dd>
                  <dt className="text-muted-foreground">Signals</dt>
                  <dd className="text-right">{shown.signals.length ? shown.signals.join(", ") : "—"}</dd>
                </dl>
                {shown.evidence.length > 0 && (
                  <ul className="flex flex-col gap-1 text-xs text-muted-foreground">
                    {shown.evidence.map((e, i) => (
                      <li key={i}>
                        {e.date ? `${e.date} · ` : ""}{e.detail} <span className="opacity-70">({e.source})</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </PanelCard>
            <PanelCard
              title="Estimated electricity use"
              value={shown.annual_kwh ? <span className="font-semibold tabular-nums">{Math.round(shown.annual_kwh).toLocaleString("en-US")} kWh/yr</span> : "—"}
            >
              <ConsumptionCard lead={shown} />
            </PanelCard>
            {shownCell ? (
              <>
                {shownCell.baseline && (
                  <PanelCard title="Baseline Need" value={<Score value={shownCell.baseline.baselineNeed} />}>
                    <BaselineNeedBlock baseline={shownCell.baseline} />
                  </PanelCard>
                )}
                {shownCell.components.outage && (
                  <PanelCard title="Outage Need" value={<Score value={shownCell.components.outage.score} />}>
                    <OutageBreakdown outage={shownCell.components.outage} />
                  </PanelCard>
                )}
                {shownCell.components.weather && (
                  <PanelCard title="Weather Need" value={<Score value={shownCell.components.weather.score} />}>
                    <WeatherBreakdown weather={shownCell.components.weather} />
                  </PanelCard>
                )}
                <PanelCard title="Propensity" value={<Score value={shownCell.propensity?.score ?? null} />}>
                  <PropensityBlock propensity={shownCell.propensity} />
                </PanelCard>
                <PanelCard title="Official NWS alerts" value={<AlertsTag feed={shownCell.live.weather.alerts} />}>
                  <NwsAlerts feed={shownCell.live.weather.alerts} />
                </PanelCard>
                <PanelCard title="Forecast signals" value={<ForecastTag feed={shownCell.live.weather.forecast} />}>
                  <ForecastSignals feed={shownCell.live.weather.forecast} />
                </PanelCard>
                <PanelCard title="ERCOT grid" value={<GridTag grid={shownCell.live.grid} />}>
                  <LiveGridSection grid={shownCell.live.grid} />
                </PanelCard>
              </>
            ) : (
              <p className="px-4 text-xs text-muted-foreground">
                {!shown.h3_index ? "This home is outside every scored area." : failed ? "The area's Need breakdown didn't load." : "Loading the area's Need breakdown…"}
              </p>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}

// Summary-line values for the live cards. Official (NWS, ERCOT) and derived (our forecast and
// grid-stress readings) keep different looks, as on the map.
function AlertsTag({ feed }: { feed: AlertFeed }) {
  if (feed.signals.length) return <Tag tone="official">{feed.signals.length} active</Tag>
  return <Tag tone={feed.stale ? "stale" : "calm"}>{feed.stale ? "Stale" : "None"}</Tag>
}

function ForecastTag({ feed }: { feed: ForecastFeed }) {
  if (feed.signals.length) {
    const high = feed.signals.some((s) => s.level === "high")
    return <Tag tone="derived">{high ? "High" : "Elevated"} · {feed.signals.length}</Tag>
  }
  return <Tag tone={feed.grid.stale || feed.spc.stale ? "stale" : "calm"}>{feed.grid.stale || feed.spc.stale ? "Stale" : "None"}</Tag>
}

function GridTag({ grid }: { grid: LiveGrid }) {
  const { condition, stressSignals } = grid
  const state = condition.state === "normal" || !condition.state ? "Normal" : (condition.title ?? condition.state)
  return (
    <span className="flex items-center gap-1">
      <Tag tone={condition.stale ? "stale" : condition.official ? "official" : "calm"}>{condition.stale ? "Stale" : state}</Tag>
      {stressSignals.length > 0 && <Tag tone="derived">{stressSignals.length} stress</Tag>}
    </span>
  )
}
