import type { Metadata } from "next"
import Link from "next/link"
import { connection } from "next/server"

import { ZoneComparison } from "@/components/grid/zone-comparison"
import { SiteHeader } from "@/components/site-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiFetch } from "@/lib/api"
import { averageGridValue, type ZoneSummary } from "@/lib/grid"
import { formatLeadMoney, valueBasis, type LeadSummary } from "@/lib/leads"

export const metadata: Metadata = { title: "Grid Zones" }

export default async function GridPage() {
  await connection()
  const [zones, leads] = await Promise.all([
    apiFetch<ZoneSummary[]>("/grid/zones"),
    apiFetch<LeadSummary>("/leads/summary"),
  ])

  if (zones.length === 0) {
    return (
      <>
        <SiteHeader title="Grid Zones" />
        <Empty>
          <EmptyHeader>
            <EmptyTitle>Grid Value is not available yet</EmptyTitle>
            <EmptyDescription>Load Zone comparisons will appear after the grid data has been refreshed.</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button variant="outline" render={<Link href="/data" />}>View data sources</Button>
            <Button variant="ghost" render={<Link href="/leads" />}>Return to leads</Button>
          </EmptyContent>
        </Empty>
      </>
    )
  }

  const sortedZones = [...zones].sort((a, b) => {
    const aValue = averageGridValue(a)
    const bValue = averageGridValue(b)
    if (aValue === null) return bValue === null ? a.name.localeCompare(b.name) : 1
    if (bValue === null) return -1
    return bValue - aValue || a.name.localeCompare(b.name)
  })
  const averageZones = sortedZones.filter((zone) => averageGridValue(zone) !== null)
  const periodsVary = new Set(averageZones.map((zone) => [...zone.history_years].sort((a, b) => a - b).join(","))).size > 1
  const basis = averageZones.length === 0
    ? "Last 12 months · Full-year history unavailable"
    : periodsVary ? "Average full calendar year · Periods vary by Load Zone" : valueBasis(averageZones[0].battery_values?.["40"])

  return (
    <>
      <SiteHeader title="Grid Zones" />
      <div className="flex min-w-0 flex-col gap-6 px-4 py-4 md:py-6 lg:px-6">
        <div className="flex flex-col gap-2">
          <h2 className="text-2xl font-semibold tracking-tight">Compare Load Zones</h2>
          <p className="font-medium">Historical grid value to Base · 40 kWh · {basis}</p>
          <p className="max-w-3xl text-sm text-muted-foreground">
            40 kWh is the comparison size. Historical estimates, not forecast revenue or customer savings.
          </p>
        </div>

        <ZoneComparison zones={zones}>
          <Card className="min-w-0" id="load-zone-comparison">
            <CardHeader>
              <CardTitle>Historical grid value to Base</CardTitle>
              <CardDescription>
                Average-year values are listed highest first. Leads include all review statuses.
                {periodsVary && " Historical periods differ; check the years shown for each Load Zone."}
              </CardDescription>
            </CardHeader>
            <CardContent className="min-w-0">
              <Table aria-label="Load Zone comparison, 40 kWh historical grid value to Base">
                <TableHeader><TableRow>
                  <TableHead scope="col">Load Zone</TableHead>
                  <TableHead scope="col" className="text-right">Average year<span className="block text-xs text-muted-foreground">$/yr</span></TableHead>
                  <TableHead scope="col" className="text-right">Last 12 months<span className="block text-xs text-muted-foreground">$/yr</span></TableHead>
                  <TableHead scope="col" className="text-right">Leads</TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {sortedZones.map((zone) => {
                    const value = zone.battery_values?.["40"]
                    const average = averageGridValue(zone)
                    const count = leads.by_zone[zone.code] ?? 0
                    return (
                      <TableRow key={zone.code}>
                        <TableCell className="min-w-40 whitespace-normal">
                          <Link href={`/grid/${encodeURIComponent(zone.code)}`} className="font-medium text-primary hover:underline">{zone.name}</Link>
                          {!zone.on_map && <Badge variant="outline" className="mt-1">Not shown on map</Badge>}
                          {average === null && <p className="mt-1 text-xs text-muted-foreground">Last 12 months · Full-year history unavailable</p>}
                          {average !== null && periodsVary && <p className="mt-1 text-xs text-muted-foreground">Full years: {[...zone.history_years].sort((a, b) => a - b).join(", ")}</p>}
                        </TableCell>
                        <TableCell className="text-right font-medium tabular-nums">{average === null ? <span aria-label="Average-year Grid Value unavailable">—</span> : formatLeadMoney(average)}</TableCell>
                        <TableCell className="text-right tabular-nums">{value && Number.isFinite(value.recent) ? formatLeadMoney(value.recent) : "Unavailable"}</TableCell>
                        <TableCell className="text-right tabular-nums">
                          {count > 0 ? <>
                            <span className="block">{count.toLocaleString("en-US")}</span>
                            <Link href={`/leads?${new URLSearchParams({ zone: zone.code, status: "all" })}`} className="text-xs text-primary hover:underline" aria-label={`View leads in ${zone.name}`}>View leads</Link>
                          </> : <span className="text-xs text-muted-foreground">No leads yet</span>}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </ZoneComparison>
      </div>
    </>
  )
}
