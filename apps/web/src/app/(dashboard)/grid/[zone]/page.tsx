import type { Metadata } from "next"
import { notFound } from "next/navigation"
import { connection } from "next/server"

import { BatteryYearsChart, MonthlyBasisChart, HourlyProfileChart, MonthlyValueChart } from "@/components/grid/zone-charts"
import { ZoneMap } from "@/components/grid/zone-map"
import { SiteHeader } from "@/components/site-header"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiFetch } from "@/lib/api"
import { formatDriverValue, scoreColor, type ZoneDetail, type ZoneSummary } from "@/lib/grid"
import { BATTERY_SIZES, formatLeadMoney } from "@/lib/leads"

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
                    {d.key === "arbitrage" && (
                      <p className="text-xs text-muted-foreground">
                        Reference battery ({battery.capacity_kwh} kWh, {battery.power_kw} kW).
                      </p>
                    )}
                    <p className="text-xs text-muted-foreground">{d.explanation}</p>
                    {d.key === "arbitrage" && Number.isFinite(zone.metrics.arbitrage_ceiling_usd) && (
                      <p className="text-xs text-muted-foreground">
                        Perfect-hindsight ceiling: {formatLeadMoney(zone.metrics.arbitrage_ceiling_usd)}/year
                        {" "}· same reference battery and period.
                      </p>
                    )}
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
                  Reference battery ({battery.capacity_kwh} kWh, {battery.power_kw} kW),{" "}
                  {Math.round(battery.round_trip_efficiency * 100)}% round-trip efficiency.
                </p>
                <p>
                  Day-ahead plans trade at real-time prices without hindsight, after losses,{" "}
                  ${battery.wear_usd_per_kwh.toFixed(2)}/kWh wear and{" "}
                  {Math.round(battery.reserve_soc * 100)}% kept for backup. Historical screening,
                  not a revenue forecast or customer savings; excludes retail margin, fees and
                  ancillary services.
                </p>
                <p>
                  The perfect-hindsight ceiling assumes every future price is known, with the
                  same battery and period.
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

        <Card>
          <CardHeader>
            <CardTitle>Historical grid value to Base</CardTitle>
            <CardDescription>
              Last 12 months · {fmtDate(zone.period_start)} – {fmtDate(zone.period_end)} · $/year
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table aria-label="Historical grid value to Base by battery size">
              <TableHeader>
                <TableRow>
                  <TableHead>Battery size</TableHead>
                  <TableHead className="text-right whitespace-normal">Day-ahead estimate</TableHead>
                  <TableHead className="text-right whitespace-normal">Perfect-hindsight ceiling</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {BATTERY_SIZES.map((kwh) => {
                  const value = zone.metrics[`battery_value_${kwh}`]
                  const ceiling = zone.metrics[`battery_ceiling_${kwh}`]
                  return (
                    <TableRow key={kwh}>
                      <TableCell>{kwh} kWh</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {Number.isFinite(value) ? formatLeadMoney(value) : "Unavailable"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {Number.isFinite(ceiling) ? formatLeadMoney(ceiling) : "Unavailable"}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <HourlyProfileChart zone={zone} />
        <div className="grid gap-6 lg:grid-cols-2">
          <MonthlyValueChart zone={zone} />
          <MonthlyBasisChart zone={zone} />
        </div>
        {!!zone.series.battery_years?.length && <BatteryYearsChart zone={zone} />}
      </div>
    </>
  )
}
