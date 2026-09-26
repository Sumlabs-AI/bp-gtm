"use client"

import * as React from "react"
import Link from "next/link"

import { BaselineNeedBlock } from "@/components/need/baseline-need"
import { ForecastSignals } from "@/components/need/forecast-signals"
import { LiveGridSection } from "@/components/need/live-grid"
import { NwsAlerts } from "@/components/need/nws-alerts"
import { PropensityBlock } from "@/components/need/propensity"
import { ConsumptionCard } from "@/components/leads/consumption-card"
import { StatusControl } from "@/components/leads/status-control"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { apiFetch } from "@/lib/api"
import { formatLeadMoney, type LeadDetail } from "@/lib/leads"
import type { CellDetail } from "@/lib/need"

/** A lead and its Cell's "why", without leaving the map. */
export function LeadDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const [lead, setLead] = React.useState<LeadDetail | null>(null)
  const [cell, setCell] = React.useState<CellDetail | null>(null)

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
      .catch(() => {})
    return () => controller.abort()
  }, [id])

  const shown = lead?.id === id ? lead : null
  const shownCell = shown && cell?.h3 === shown.h3_index ? cell : null

  return (
    <Sheet open={id !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{shown?.address ?? "Lead"}</SheetTitle>
          <SheetDescription>
            {shown ? `${shown.city ?? ""} ${shown.zip ?? ""} · ${shown.load_zone ?? "no load zone"}` : "Loading…"}
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
        {shown && (
          <div className="flex flex-col gap-6 overflow-y-auto pb-6">
            <section className="flex flex-col gap-2 px-4 text-sm">
              <h3 className="font-medium">This home</h3>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                <dt className="text-muted-foreground">Estimated use</dt>
                <dd className="text-right tabular-nums">{shown.annual_kwh ? `${Math.round(shown.annual_kwh).toLocaleString("en-US")} kWh/yr` : "—"}</dd>
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
              <StatusControl id={shown.id} status={shown.status} />
            </section>
            <ConsumptionCard lead={shown} />
            {shownCell ? (
              <>
                {shownCell.baseline && <BaselineNeedBlock baseline={shownCell.baseline} />}
                <PropensityBlock propensity={shownCell.propensity} />
                <NwsAlerts feed={shownCell.live.weather.alerts} />
                <ForecastSignals feed={shownCell.live.weather.forecast} />
                <LiveGridSection grid={shownCell.live.grid} />
              </>
            ) : (
              <p className="px-4 text-xs text-muted-foreground">
                {shown.h3_index ? "Loading the area's Need breakdown…" : "This home is outside every scored area."}
              </p>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
