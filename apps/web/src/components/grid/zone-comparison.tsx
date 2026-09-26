"use client"

import { useState, type ReactNode } from "react"
import Link from "next/link"

import { DriverBars } from "@/components/grid/driver-bars"
import { ZoneMap } from "@/components/grid/zone-map"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldLabel } from "@/components/ui/field"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import type { ZoneSummary } from "@/lib/grid"

const DRIVER_HELP: Record<string, string> = {
  arbitrage: "Day-ahead trading estimate for the reference battery (39.2 kWh, 11.5 kW), after losses, wear and backup reserve.",
  congestion: "Average upward price gap against the ERCOT hub. Periods at or below the hub contribute zero.",
  scarcity: "Hours with real-time prices at or above $1,000/MWh.",
  surprise: "Average absolute gap between day-ahead and real-time prices.",
  negative_prices: "Share of real-time intervals with prices below $0/MWh.",
}

export function ZoneComparison({ zones, children }: { zones: ZoneSummary[]; children: ReactNode }) {
  const [metric, setMetric] = useState("average")
  const drivers = zones[0]?.drivers ?? []

  return (
    <>
      <div className="grid min-w-0 items-start gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        {children}
        <div className="flex min-w-0 flex-col gap-2">
          <Field>
            <FieldLabel htmlFor="grid-map-metric">Color map by</FieldLabel>
            <NativeSelect id="grid-map-metric" value={metric} onChange={(event) => setMetric(event.target.value)} className="w-full">
              <NativeSelectOption value="average">Grid Value · 40 kWh · Average year ($/yr)</NativeSelectOption>
              <NativeSelectOption value="grid_value">Zone Economics Score · Last 12 months</NativeSelectOption>
              {drivers.map((driver) => <NativeSelectOption key={driver.key} value={driver.key}>{driver.label} · Relative score, last 12 months</NativeSelectOption>)}
            </NativeSelect>
          </Field>
          <ZoneMap zones={zones} metric={metric} className="h-80 min-w-0 xl:h-96" />
          <p className="text-xs text-muted-foreground">
            Approximate Load Zone boundaries. All {zones.length} Load Zones, including those not drawn,
            are in the <a href="#load-zone-comparison" className="underline underline-offset-4">comparison table</a>.
          </p>
        </div>
      </div>

      <section aria-labelledby="price-analysis" className="flex min-w-0 flex-col gap-4">
        <div className="flex flex-col gap-1">
          <h3 id="price-analysis" className="text-lg font-semibold tracking-tight">Price analysis · Last 12 months</h3>
          <p className="text-sm font-medium">Zone Economics Score · Relative to {zones.length} Load Zones</p>
          <p className="text-sm text-muted-foreground">
            A weighted comparison of five grid-price measures. The score is a relative index, not a
            percentage of Grid Value or a measure of backup need. Each driver is scaled 0–100 across
            these Load Zones, then combined using the weights below.
          </p>
        </div>
        <div className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {zones.map((zone) => <Card key={zone.code} size="sm" className="min-w-0">
            <CardHeader>
              <CardTitle className="flex items-baseline justify-between gap-2">
                <Link href={`/grid/${encodeURIComponent(zone.code)}`} className="text-primary hover:underline">{zone.name}</Link>
                <span className="shrink-0 tabular-nums">{zone.grid_value_score.toFixed(0)}/100</span>
              </CardTitle>
              <CardDescription>{zone.primary_reason}</CardDescription>
            </CardHeader>
            <CardContent className="min-w-0 overflow-x-auto">
              <div className="min-w-72"><DriverBars drivers={zone.drivers} /></div>
            </CardContent>
          </Card>)}
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {drivers.map((driver) => <div key={driver.key} className="flex flex-col gap-1">
            <p className="text-sm font-medium">{driver.label} · {Math.round(driver.weight * 100)}%</p>
            <p className="text-xs text-muted-foreground">{DRIVER_HELP[driver.key]}</p>
          </div>)}
        </div>
      </section>
    </>
  )
}
