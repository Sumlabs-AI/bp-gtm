import type { Metadata } from "next"
import Link from "next/link"
import { notFound } from "next/navigation"
import { connection } from "next/server"
import { CalculatorIcon } from "lucide-react"

import { Disclosure } from "@/components/disclosure"
import { BatteryYearsChart, MonthlyBasisChart, HourlyProfileChart, MonthlyValueChart } from "@/components/grid/zone-charts"
import { ZoneMap } from "@/components/grid/zone-map"
import { SiteHeader } from "@/components/site-header"
import { Badge } from "@/components/ui/badge"
import { buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiFetch } from "@/lib/api"
import { formatDriverValue, type ZoneDetail, type ZoneSummary } from "@/lib/grid"
import { BATTERY_SIZES, formatLeadMoney, valueBasis, type LeadSummary } from "@/lib/leads"

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "America/Chicago" })

export async function generateMetadata(props: PageProps<"/grid/[zone]">): Promise<Metadata> {
  const { zone: code } = await props.params
  const zones = await apiFetch<ZoneSummary[]>("/grid/zones")
  return { title: zones.find((zone) => zone.code === code)?.name ?? "Grid zone not found" }
}

export default async function ZonePage(props: PageProps<"/grid/[zone]">) {
  await connection()
  const { zone: code } = await props.params
  const [zones, leadSummary] = await Promise.all([
    apiFetch<ZoneSummary[]>("/grid/zones"),
    apiFetch<LeadSummary>("/leads/summary"),
  ])
  if (!zones.some((z) => z.code === code)) notFound()
  const zone = await apiFetch<ZoneDetail>(`/grid/zones/${code}`)
  const { battery } = zone.assumptions
  const leadCount = leadSummary.by_zone[zone.code] ?? 0
  const leadsHref = `/leads?${new URLSearchParams({ zone: zone.code, status: "all" })}`
  const basis = valueBasis(zone.battery_values?.["40"])
  const hasAverage = zone.battery_values?.["40"].first_year != null && zone.battery_values?.["40"].last_year != null

  return (
    <>
      <SiteHeader title={zone.name} parent={{ title: "Grid Zones", href: "/grid" }} />
      <div className="flex min-w-0 flex-col gap-6 px-4 py-4 md:py-6 lg:px-6">
        <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 flex-col gap-2">
            <h2 className="text-2xl font-semibold tracking-tight">{zone.name}</h2>
            <p className="text-sm text-muted-foreground">{zone.description}</p>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{zone.code}</Badge>
              <span className="text-sm text-muted-foreground">
                {leadCount > 0 ? `${leadCount.toLocaleString("en-US")} leads` : "No leads yet"}
              </span>
            </div>
          </div>
          {leadCount > 0 && <Link href={leadsHref} className={buttonVariants({ variant: "outline" })}>
            View leads
          </Link>}
        </div>

        <Card className="min-w-0">
          <CardHeader className="min-w-0">
            <CardTitle>Historical grid value to Base</CardTitle>
            <CardDescription>
              Day-ahead estimates · $/year. Last 12 months: {fmtDate(zone.period_start)} – {fmtDate(zone.period_end)}.
            </CardDescription>
          </CardHeader>
          <CardContent className="min-w-0 overflow-x-auto">
            <Table aria-label="Historical grid value to Base by battery size">
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">Battery size</TableHead>
                  <TableHead scope="col" className="text-right whitespace-normal">{basis}</TableHead>
                  {hasAverage && <TableHead scope="col" className="text-right whitespace-normal">Last 12 months</TableHead>}
                  <TableHead scope="col" className="text-right whitespace-normal">
                    Perfect-hindsight ceiling, {hasAverage ? "average year" : "last 12 months"}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {BATTERY_SIZES.map((kwh) => {
                  const value = zone.battery_values?.[kwh]
                  return (
                    <TableRow key={kwh}>
                      <TableCell>{kwh} kWh</TableCell>
                      <TableCell className="text-right tabular-nums">
                        <span className="font-semibold">{value && Number.isFinite(value.value) ? formatLeadMoney(value.value) : "Unavailable"}</span>
                      </TableCell>
                      {hasAverage && <TableCell className="text-right tabular-nums">
                        {value && Number.isFinite(value.recent) ? formatLeadMoney(value.recent) : "Unavailable"}
                      </TableCell>}
                      <TableCell className="text-right tabular-nums">
                        {value && Number.isFinite(value.ceiling) ? formatLeadMoney(value.ceiling) : "Unavailable"}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        {!!zone.series.battery_years?.length && <BatteryYearsChart zone={zone} />}

        <section aria-labelledby="price-analysis" className="flex min-w-0 flex-col gap-4">
          <h3 id="price-analysis" className="text-lg font-semibold tracking-tight">Price analysis · Last 12 months</h3>
          <div className="flex min-w-0 flex-col gap-6">
            <Card className="min-w-0">
              <CardHeader className="min-w-0">
                <CardTitle>Zone Economics Score</CardTitle>
                <CardDescription>
                  Relative comparison across {zones.length} Load Zones · {fmtDate(zone.period_start)} – {fmtDate(zone.period_end)}
                </CardDescription>
              </CardHeader>
              <CardContent className="flex min-w-0 flex-col gap-3">
                <p className="text-3xl font-semibold tabular-nums">{zone.grid_value_score.toFixed(0)}<span className="text-sm font-normal text-muted-foreground">/100</span></p>
                <p className="text-sm text-muted-foreground">
                  A weighted comparison of five grid-price measures. {zone.grid_value_score.toFixed(0)}/100
                  {" "}is a relative index, not a percentage of Grid Value or a measure of backup need.
                </p>
                <p className="text-sm">{zone.primary_reason}</p>
              </CardContent>
            </Card>

            <div className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {zone.drivers.map((d) => (
                <Card key={d.key} size="sm" className="min-w-0">
                  <CardHeader className="min-w-0">
                    <CardTitle className="flex flex-wrap items-baseline justify-between gap-2">
                      <span>{d.label}</span>
                      <span className="tabular-nums">{formatDriverValue(d)}</span>
                    </CardTitle>
                    <CardDescription>
                      Score {d.score.toFixed(0)}/100 · {Math.round(d.weight * 100)}% of Zone Economics Score
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="flex min-w-0 flex-col gap-2">
                    <Progress value={d.score} aria-label={`${d.label} score`} />
                    {d.key === "arbitrage" && <p className="text-xs text-muted-foreground">
                      Reference battery ({battery.capacity_kwh} kWh, {battery.power_kw} kW).
                    </p>}
                    <p className="text-xs text-muted-foreground">{d.explanation}</p>
                    {d.key === "arbitrage" && Number.isFinite(zone.metrics.arbitrage_ceiling_usd) && <p className="text-xs text-muted-foreground">
                      Perfect-hindsight ceiling: {formatLeadMoney(zone.metrics.arbitrage_ceiling_usd)}/year
                      {" "}· same reference battery and period.
                    </p>}
                  </CardContent>
                </Card>
              ))}
            </div>

            <p className="text-sm text-muted-foreground">
              For the reference battery, the top 10 days produced {zone.metrics.top10_days_share.toFixed(0)}%
              {" "}of the last 12 months&apos; battery value. Typical daily spread (top vs. bottom 4 hours):
              {" "}${zone.metrics.daily_spread.toFixed(2)}/MWh.
            </p>
            <HourlyProfileChart zone={zone} />
            <div className="grid min-w-0 gap-6 lg:grid-cols-2">
              <MonthlyValueChart zone={zone} />
              <MonthlyBasisChart zone={zone} />
            </div>
          </div>
        </section>

        <Disclosure title="How Grid Value is estimated" icon={CalculatorIcon}>
          <div className="flex min-w-0 flex-col gap-3 text-sm text-muted-foreground">
            <p>
              Grid Value averages the available full calendar years, weighting each year equally.
              Without full-year history, it uses the last 12 months.
            </p>
            {zone.history_years.length > 0 && <p>
              Full calendar years included: {[...zone.history_years].sort((a, b) => a - b).join(", ")}.
            </p>}
            <p>
              Day-ahead plans trade at real-time ERCOT prices without hindsight, after energy losses,
              {" "}${battery.wear_usd_per_kwh.toFixed(2)}/kWh battery wear and {Math.round(battery.reserve_soc * 100)}%
              {" "}kept for backup. Round-trip efficiency is {Math.round(battery.round_trip_efficiency * 100)}%.
            </p>
            <p>
              Grid Value Ceiling assumes every future price is known, using the same battery,
              losses, wear, backup reserve and period. It is a benchmark, not a sales figure.
            </p>
            <p>
              The score&apos;s battery driver and monthly chart use a reference battery
              {" "}({battery.capacity_kwh} kWh, {battery.power_kw} kW), separate from the 25 / 40 / 50 kWh comparisons.
              These are analysis assumptions, not published battery specifications.
            </p>
            <p>
              Historical energy-trading estimates, not forecast revenue or customer savings.
              Excludes retail margin, fees and ancillary services. Values apply to this Load Zone,
              not an individual home&apos;s electricity use.
            </p>
          </div>
        </Disclosure>

        <Card className="min-w-0">
          <CardHeader className="min-w-0">
            <CardTitle>Load Zone map</CardTitle>
            <CardDescription>Approximate Load Zone boundaries. Colors compare 40 kWh Grid Value.</CardDescription>
          </CardHeader>
          <CardContent className="min-w-0">
            {zone.on_map ? <ZoneMap zones={zones} selected={zone.code} className="h-80 min-w-0 w-full" /> : <p className="text-sm text-muted-foreground">
              This Load Zone has no contiguous geography, so it is not shown on the map.
            </p>}
          </CardContent>
        </Card>
      </div>
    </>
  )
}
