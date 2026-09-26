import type { Metadata } from "next"
import Link from "next/link"
import { connection } from "next/server"

import { DriverBars } from "@/components/grid/driver-bars"
import { ZoneMap } from "@/components/grid/zone-map"
import { SiteHeader } from "@/components/site-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"
import { apiFetch } from "@/lib/api"
import { scoreColor, type ZoneSummary } from "@/lib/grid"

export const metadata: Metadata = { title: "Grid Zones" }

export default async function GridPage() {
  await connection() // scores change when the API recomputes; never prerender at build
  const zones = await apiFetch<ZoneSummary[]>("/grid/zones")
  const drivers = zones[0]?.drivers ?? []

  if (zones.length === 0) {
    return (
      <>
        <SiteHeader title="Grid Zones" />
        <Empty>
          <EmptyHeader>
            <EmptyTitle>Grid scores are not available yet</EmptyTitle>
            <EmptyDescription>Zone rankings will appear after the grid data has been refreshed.</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button variant="outline" render={<Link href="/data" />}>View data sources</Button>
            <Button variant="ghost" render={<Link href="/leads" />}>Return to leads</Button>
          </EmptyContent>
        </Empty>
      </>
    )
  }

  return (
    <>
      <SiteHeader title="Grid Zones" />
      <div className="flex flex-col gap-6 px-4 py-4 md:py-6 lg:px-6">
        <div className="flex flex-col gap-2">
          <h2 className="text-2xl font-semibold tracking-tight">
            Where should Base want more batteries?
          </h2>
          <p className="max-w-3xl text-sm text-muted-foreground">
            A historical grid backtest ranks ERCOT load zones using the last 12 months of real-time
            and day-ahead prices. Values assume perfect hindsight and are not a revenue forecast.
            Click a zone to see its drivers.
          </p>
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">Resolution: ERCOT load zone</Badge>
            <Badge variant="outline">Boundaries approximate</Badge>
            <Badge variant="outline">Scores relative: 100 = best zone</Badge>
          </div>
        </div>

        <div className="grid gap-6 xl:grid-cols-5">
          <ZoneMap zones={zones} className="h-[560px] xl:col-span-3" />

          <div className="flex flex-col gap-3 xl:col-span-2">
            {zones.map((z) => (
              <Link key={z.code} href={`/grid/${z.code}`} className="group">
                <Card size="sm" className="transition-colors group-hover:bg-muted/50">
                  <CardHeader>
                    <CardTitle className="flex items-center gap-3">
                      <span className="w-5 text-muted-foreground tabular-nums">{z.rank}</span>
                      <span>{z.name}</span>
                      {!z.on_map && (
                        <Badge variant="secondary" className="font-normal">
                          not on map
                        </Badge>
                      )}
                      <span
                        className="ml-auto rounded-md px-2 py-0.5 text-sm font-semibold tabular-nums"
                        style={{ background: scoreColor(z.grid_value_score) }}
                      >
                        {z.grid_value_score.toFixed(0)}
                      </span>
                    </CardTitle>
                    <CardDescription className="pl-8">{z.primary_reason}</CardDescription>
                  </CardHeader>
                  <CardContent className="pl-12">
                    <DriverBars drivers={z.drivers} />
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>How the Grid Value Score works</CardTitle>
            <CardDescription>
              Each driver is measured from ERCOT prices, then scaled 0–100 across the load zones
              (worst zone = 0, best = 100). The Grid Value Score is their weighted average.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            {drivers.map((d) => (
              <div key={d.key} className="flex flex-col gap-1">
                <div className="flex items-baseline justify-between">
                  <span className="text-sm font-medium">{d.label}</span>
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {Math.round(d.weight * 100)}%
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">{DRIVER_HELP[d.key]}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </>
  )
}

const DRIVER_HELP: Record<string, string> = {
  arbitrage:
    "Backtest: best daily charge/discharge schedule for one Base battery on real-time prices.",
  congestion: "How far zone prices rise above the ERCOT hub average when they separate.",
  scarcity: "Hours per year with real-time prices at or above $1,000/MWh.",
  surprise: "Average gap between real-time and day-ahead prices; rewards flexibility.",
  negative_prices: "Share of intervals where power is free or negatively priced.",
}
