"use client"

import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, XAxis, YAxis } from "recharts"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import type { ZoneDetail } from "@/lib/grid"

const monthLabel = (m: string) =>
  new Date(`${m}-01T12:00:00`).toLocaleDateString("en-US", { month: "short", year: "2-digit" })

export function HourlyProfileChart({ zone }: { zone: ZoneDetail }) {
  const config = {
    zone: { label: zone.name, color: "#15803d" },
    hub: { label: "ERCOT hub avg", color: "#64748b" },
  } satisfies ChartConfig
  return (
    <Card>
      <CardHeader>
        <CardTitle>Average price by hour of day</CardTitle>
        <CardDescription>
          Real-time $/MWh, local time. The gap between the cheap midday/overnight hours and
          the evening peak is what a battery captures.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer config={config} className="aspect-auto h-64 w-full">
          <LineChart data={zone.series.hourly_profile} margin={{ left: 4, right: 12 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="hour" tickLine={false} axisLine={false} tickFormatter={(h) => `${h}h`} />
            <YAxis tickLine={false} axisLine={false} width={40} tickFormatter={(v) => `$${v}`} />
            <ChartTooltip
              content={<ChartTooltipContent labelFormatter={(_, p) => `${p[0]?.payload.hour}:00`} />}
            />
            <ChartLegend content={<ChartLegendContent />} />
            <Line dataKey="zone" stroke="var(--color-zone)" strokeWidth={2} dot={false} />
            <Line
              dataKey="hub"
              stroke="var(--color-hub)"
              strokeWidth={1.5}
              strokeDasharray="4 4"
              dot={false}
            />
          </LineChart>
        </ChartContainer>
      </CardContent>
    </Card>
  )
}

export function MonthlyValueChart({ zone }: { zone: ZoneDetail }) {
  const { battery } = zone.assumptions
  const config = {
    arbitrage_usd: { label: "Day-ahead estimate ($)", color: "#15803d" },
  } satisfies ChartConfig
  return (
    <Card>
      <CardHeader>
        <CardTitle>Battery value by month</CardTitle>
        <CardDescription>
          Day-ahead estimates for the reference battery ({battery.capacity_kwh} kWh,{" "}
          {battery.power_kw} kW) · $/month. Spiky months mean value depends on a few scarcity events.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer config={config} className="aspect-auto h-64 w-full">
          <BarChart data={zone.series.monthly} margin={{ left: 4, right: 12 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="month" tickLine={false} axisLine={false} tickFormatter={monthLabel} />
            <YAxis tickLine={false} axisLine={false} width={40} tickFormatter={(v) => `$${v}`} />
            <ChartTooltip
              content={<ChartTooltipContent labelFormatter={(m) => monthLabel(String(m))} />}
            />
            <Bar dataKey="arbitrage_usd" fill="var(--color-arbitrage_usd)" radius={4} />
          </BarChart>
        </ChartContainer>
      </CardContent>
    </Card>
  )
}

export function BatteryYearsChart({ zone }: { zone: ZoneDetail }) {
  const config = {
    "25": { label: "25 kWh", color: "#86c896" },
    "40": { label: "40 kWh", color: "#22c55e" },
    "50": { label: "50 kWh", color: "#15803d" },
  } satisfies ChartConfig
  return (
    <Card>
      <CardHeader>
        <CardTitle>Realistic value by year</CardTitle>
        <CardDescription>
          Day-ahead estimates for full calendar years · $/year.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer config={config} className="aspect-auto h-56 w-full">
          <BarChart data={zone.series.battery_years ?? []} margin={{ left: 4, right: 12 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="year" tickLine={false} axisLine={false} />
            <YAxis tickLine={false} axisLine={false} width={40} tickFormatter={(v) => `$${v}`} />
            <ChartTooltip
              content={<ChartTooltipContent labelFormatter={(_, p) => String(p[0]?.payload.year)} />}
            />
            <ChartLegend content={<ChartLegendContent />} />
            <Bar dataKey="25" fill="var(--color-25)" radius={4} />
            <Bar dataKey="40" fill="var(--color-40)" radius={4} />
            <Bar dataKey="50" fill="var(--color-50)" radius={4} />
          </BarChart>
        </ChartContainer>
      </CardContent>
    </Card>
  )
}

export function MonthlyBasisChart({ zone }: { zone: ZoneDetail }) {
  const config = {
    avg_basis: { label: "Zone − hub ($/MWh)", color: "#15803d" },
  } satisfies ChartConfig
  return (
    <Card>
      <CardHeader>
        <CardTitle>Price vs. the rest of the grid</CardTitle>
        <CardDescription>
          Monthly average of zone price minus ERCOT hub average. Above zero means power is
          scarcer here than elsewhere, usually from transmission congestion.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer config={config} className="aspect-auto h-64 w-full">
          <BarChart data={zone.series.monthly} margin={{ left: 4, right: 12 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="month" tickLine={false} axisLine={false} tickFormatter={monthLabel} />
            <YAxis tickLine={false} axisLine={false} width={40} tickFormatter={(v) => `$${v}`} />
            <ChartTooltip
              content={<ChartTooltipContent labelFormatter={(m) => monthLabel(String(m))} />}
            />
            <Bar dataKey="avg_basis" radius={4}>
              {zone.series.monthly.map((m) => (
                <Cell
                  key={m.month}
                  fill={m.avg_basis >= 0 ? "var(--color-avg_basis)" : "var(--muted-foreground)"}
                />
              ))}
            </Bar>
          </BarChart>
        </ChartContainer>
      </CardContent>
    </Card>
  )
}
