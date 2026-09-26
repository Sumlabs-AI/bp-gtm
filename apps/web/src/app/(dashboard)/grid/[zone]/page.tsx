import Link from "next/link"
import { notFound } from "next/navigation"
import { connection } from "next/server"
import { ArrowLeftIcon } from "lucide-react"

import { BatteryYearsChart, MonthlyBasisChart, HourlyProfileChart, MonthlyValueChart } from "@/components/grid/zone-charts"
import { ZoneMap } from "@/components/grid/zone-map"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { apiFetch } from "@/lib/api"
import { formatDriverValue, scoreColor, type ZoneDetail, type ZoneSummary } from "@/lib/grid"

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })

export default async function ZonePage(props: PageProps<"/grid/[zone]">) {
  await connection()
  const { zone: code } = await props.params
  const zones = await apiFetch<ZoneSummary[]>("/grid/zones")
  if (!zones.some((z) => z.code === code)) notFound()
  const zone = await apiFetch<ZoneDetail>(`/grid/zones/${code}`)
  const { battery } = zone.assumptions
  const realisticValue = zone.metrics.arbitrage_usd
  const ceilingValue = zone.metrics.arbitrage_ceiling_usd
  const capturedPct = ceilingValue > 0 ? Math.round((realisticValue / ceilingValue) * 100) : null

  return (
    <div className="flex flex-col gap-6 px-4 py-4 md:py-6 lg:px-6">
      <Link
        href="/grid"
        className="flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeftIcon className="size-4" /> All zones
      </Link>

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
              <h2 className="text-2xl font-semibold tracking-tight">
                {zone.name} <span className="font-mono text-base text-muted-foreground">{zone.code}</span>
              </h2>
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
              <CardTitle>Zone battery value</CardTitle>
              <CardDescription>Last 12 months · {battery.capacity_kwh} kWh battery</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-xs text-muted-foreground">Realistic</p>
                  <p className="text-xl font-semibold tabular-nums">
                    {formatDriverValue({ value: realisticValue, unit: "$/battery/yr" })}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Perfect-hindsight ceiling</p>
                  <p className="text-xl font-semibold tabular-nums">
                    {formatDriverValue({ value: ceilingValue, unit: "$/battery/yr" })}
                  </p>
                </div>
              </div>
              {capturedPct !== null && (
                <p className="text-xs text-muted-foreground">
                  Realistic plan captured {capturedPct}% of the ceiling.
                </p>
              )}
            </CardContent>
          </Card>
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
                Backtest: a daily plan from day-ahead prices, traded at 15-minute real-time prices
                after efficiency losses, wear, and a 20% backup reserve. The ceiling assumes perfect
                hindsight. Historical screening, not a P&amp;L forecast; excludes ancillary services,
                retail margin, and fees.
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
      {zone.series.battery_years?.length ? <BatteryYearsChart zone={zone} /> : null}
    </div>
  )
}
