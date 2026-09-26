import type { Metadata } from "next"
import { notFound } from "next/navigation"
import { connection } from "next/server"

import { MonthlyBasisChart, HourlyProfileChart, MonthlyValueChart } from "@/components/grid/zone-charts"
import { ZoneMap } from "@/components/grid/zone-map"
import { SiteHeader } from "@/components/site-header"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { apiFetch } from "@/lib/api"
import { formatDriverValue, scoreColor, type ZoneDetail, type ZoneSummary } from "@/lib/grid"

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })

export async function generateMetadata(props: PageProps<"/grid/[zone]">): Promise<Metadata> {
  const { zone: code } = await props.params
  const zones = await apiFetch<ZoneSummary[]>("/grid/zones")
  return { title: zones.find((zone) => zone.code === code)?.name ?? "Grid zone not found" }
}

export default async function ZonePage(props: PageProps<"/grid/[zone]">) {
  await connection()
  const { zone: code } = await props.params
  const zones = await apiFetch<ZoneSummary[]>("/grid/zones")
  if (!zones.some((z) => z.code === code)) notFound()
  const zone = await apiFetch<ZoneDetail>(`/grid/zones/${code}`)
  const { battery } = zone.assumptions

  return (
    <>
      <SiteHeader title={zone.name} parent={{ title: "Grid Zones", href: "/grid" }} />
      <div className="flex flex-col gap-6 px-4 py-4 md:py-6 lg:px-6">
        <div className="grid gap-6 xl:grid-cols-5">
          <div className="flex flex-col gap-4 xl:col-span-3">
            <div className="flex items-start gap-4">
              <div
                className="flex size-20 shrink-0 flex-col items-center justify-center rounded-xl"
                style={{ background: scoreColor(zone.grid_value_score) }}
              >
                <span className="text-3xl font-semibold tabular-nums">
                  {zone.grid_value_score.toFixed(0)}
                </span>
                <span className="text-[10px] uppercase tracking-wide">Grid value</span>
              </div>
              <div className="flex flex-col gap-1">
                <p className="font-mono text-sm text-muted-foreground">{zone.code}</p>
                <p className="text-sm text-muted-foreground">{zone.description}</p>
                <p className="text-sm">
                  <span className="font-medium">
                    Rank {zone.rank} of {zones.length}.
                  </span>{" "}
                  {zone.primary_reason}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">
                {fmtDate(zone.period_start)} – {fmtDate(zone.period_end)}
              </Badge>
              <Badge variant="outline">Resolution: ERCOT load zone</Badge>
              <Badge variant="outline">Scores relative: 100 = best zone</Badge>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              {zone.drivers.map((d) => (
                <Card key={d.key} size="sm">
                  <CardHeader>
                    <CardTitle className="flex items-baseline justify-between">
                      <span>{d.label}</span>
                      <span className="text-base tabular-nums">{formatDriverValue(d)}</span>
                    </CardTitle>
                    <CardDescription className="text-xs">
                      Score {d.score.toFixed(0)}/100 · {Math.round(d.weight * 100)}% of Grid Value
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-2">
                    <Progress value={d.score} aria-label={`${d.label} score`} />
                    <p className="text-xs text-muted-foreground">{d.explanation}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-4 xl:col-span-2">
            {zone.on_map ? (
              <ZoneMap zones={zones} selected={zone.code} className="h-[400px]" />
            ) : (
              <Card>
                <CardContent className="text-sm text-muted-foreground">
                  This zone has no contiguous geography, so it isn&apos;t drawn on the map.
                </CardContent>
              </Card>
            )}
            <Card size="sm">
              <CardHeader>
                <CardTitle>Assumptions</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-1 text-xs text-muted-foreground">
                <p>
                  Battery: {battery.capacity_kwh} kWh, {battery.power_kw} kW,{" "}
                  {Math.round(battery.round_trip_efficiency * 100)}% round-trip efficiency.
                </p>
                <p>
                  Historical grid backtest: best possible daily charge/discharge schedule on 15-minute real-time
                  prices, with perfect hindsight. Historical screening, not a P&amp;L forecast;
                  excludes ancillary services and retail tariffs.
                </p>
                <p>
                  Top 10 days produced {zone.metrics.top10_days_share.toFixed(0)}% of the year&apos;s
                  battery value. Typical daily spread (top vs. bottom 4 hours): $
                  {zone.metrics.daily_spread.toFixed(2)}/MWh.
                </p>
              </CardContent>
            </Card>
          </div>
        </div>

        <HourlyProfileChart zone={zone} />
        <div className="grid gap-6 lg:grid-cols-2">
          <MonthlyValueChart zone={zone} />
          <MonthlyBasisChart zone={zone} />
        </div>
      </div>
    </>
  )
}
