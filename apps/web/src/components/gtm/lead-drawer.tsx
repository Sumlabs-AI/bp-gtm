"use client"

import * as React from "react"

import { BaselineNeedBlock } from "@/components/need/baseline-need"
import { ForecastSignals } from "@/components/need/forecast-signals"
import { LiveGridSection } from "@/components/need/live-grid"
import { NwsAlerts } from "@/components/need/nws-alerts"
import { OutageBreakdown } from "@/components/need/outage-breakdown"
import { PropensityBlock } from "@/components/need/propensity"
import { Score } from "@/components/need/score-parts"
import { WeatherBreakdown } from "@/components/need/weather-breakdown"
import { ConsumptionCard } from "@/components/leads/consumption-card"
import { AddressCard, EvidenceList, HomeProfile, TalkingPoints, ValueSection, talkingPoints } from "@/components/leads/lead-sections"
import { PanelCard, Tag } from "@/components/gtm/panel-card"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { apiFetch } from "@/lib/api"
import type { ZoneDetail } from "@/lib/grid"
import { formatLeadMoney, type LeadDetail } from "@/lib/leads"
import type { AlertFeed, CellDetail, ForecastFeed, LiveGrid } from "@/lib/need"

/** Everything about a lead, without leaving the map: the home, then its area (the Cell). */
export function LeadDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const [lead, setLead] = React.useState<LeadDetail | null>(null)
  const [cell, setCell] = React.useState<CellDetail | null>(null)
  const [zone, setZone] = React.useState<ZoneDetail | null>(null)
  const [error, setError] = React.useState<{ id: number; message: string } | null>(null)

  React.useEffect(() => {
    if (id === null) return
    const controller = new AbortController()
    const signal = controller.signal
    apiFetch<LeadDetail>(`/leads/${id}`, { signal })
      .then((detail) => {
        setLead(detail)
        // Optional extras: the Cell's Need and the Load Zone's year-by-year battery value.
        if (detail.load_zone) {
          apiFetch<ZoneDetail>(`/grid/zones/${encodeURIComponent(detail.load_zone)}`, { signal }).then(setZone).catch(() => {})
        }
        if (detail.h3_index) {
          return apiFetch<CellDetail>(`/need/cells/${detail.h3_index}`, { signal }).then(setCell)
        }
        setCell(null)
      })
      .catch((e: Error) => {
        if (!signal.aborted) setError({ id, message: e.message })
      })
    return () => controller.abort()
  }, [id])

  const shown = lead?.id === id ? lead : null
  const shownCell = shown && cell?.h3 === shown.h3_index ? cell : null
  const shownZone = shown && zone?.code === shown.load_zone ? zone : null
  const failed = error?.id === id ? error.message : null
  const points = shown ? talkingPoints(shown) : []

  return (
    <Sheet open={id !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="sm:max-w-md" showCloseButton={false}>
        <SheetHeader className="pb-2">
          <SheetTitle className="sr-only">{shown?.address ?? "Lead"}</SheetTitle>
          <SheetDescription className={shown ? "sr-only" : undefined}>
            {shown ? `${shown.city ?? ""} ${shown.zip ?? ""}` : failed ? "Couldn't load this lead" : "Loading…"}
          </SheetDescription>
        </SheetHeader>
        {failed && <p className="px-4 text-xs text-destructive">{failed}</p>}
        {shown && (
          <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pb-6">
            <div className="px-4 pb-2">
              <AddressCard lead={shown} />
            </div>

            <SectionTitle title="Home" hint="This property: value, use and records" />
            <PanelCard
              title="Priority value"
              value={shown.expected_value !== null ? <span className="font-semibold tabular-nums">{formatLeadMoney(shown.expected_value)}/yr</span> : "—"}
            >
              <ValueSection lead={shown} zone={shownZone} />
            </PanelCard>
            <PanelCard
              title="Estimated electricity use"
              value={shown.annual_kwh ? <span className="font-semibold tabular-nums">{Math.round(shown.annual_kwh).toLocaleString("en-US")} kWh/yr</span> : "—"}
            >
              <ConsumptionCard lead={shown} />
            </PanelCard>
            <PanelCard
              title="Home profile"
              value={<span className="tabular-nums text-muted-foreground">{[shown.heated_sqft ? `${Math.round(shown.heated_sqft).toLocaleString("en-US")} sqft` : null, shown.year_built].filter(Boolean).join(" · ") || "—"}</span>}
            >
              <HomeProfile lead={shown} />
            </PanelCard>
            <PanelCard title="Talking points" value={<span className="text-muted-foreground">{points.length || "—"}</span>}>
              <TalkingPoints points={points} />
            </PanelCard>
            <PanelCard title="Evidence & sources" value={<span className="text-muted-foreground">{shown.evidence.length || "—"}</span>}>
              <EvidenceList lead={shown} />
            </PanelCard>

            <SectionTitle title="Area" hint="The home's H3 Cell: why backup power matters here, and now" />
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
                <p className="px-4 font-mono text-[11px] text-muted-foreground">Cell {shownCell.h3}</p>
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

function SectionTitle({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="flex items-baseline gap-2 px-4 pt-3">
      <h3 className="text-xs font-semibold tracking-wider text-muted-foreground uppercase">{title}</h3>
      <span className="truncate text-[11px] text-muted-foreground">{hint}</span>
    </div>
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
