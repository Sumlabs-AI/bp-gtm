"use client"

import { Bar, BarChart, CartesianGrid, ErrorBar, XAxis, YAxis } from "recharts"

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { formatKwh, type Consumption } from "@/lib/leads"

const months = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
]

const config = {
  estimate: { label: "Estimated Consumption", color: "#15803d" },
  range: { label: "Likely range", color: "#86c896" },
} satisfies ChartConfig

export function ConsumptionChart({ consumption }: { consumption: Consumption }) {
  const data = consumption.monthly_kwh.map((estimate, index) => {
    const low = estimate * consumption.low_kwh / consumption.annual_kwh
    const high = estimate * consumption.high_kwh / consumption.annual_kwh

    return {
      month: months[index],
      estimate,
      low,
      high,
      range: [estimate - low, high - estimate],
    }
  })

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <p className="text-sm font-medium">Monthly estimate · kWh</p>
      <ChartContainer config={config} className="aspect-auto h-64 min-w-0 w-full">
        <BarChart accessibilityLayer data={data} margin={{ top: 8, left: 0, right: 4 }}>
          <CartesianGrid vertical={false} />
          <XAxis
            dataKey="month"
            tickLine={false}
            axisLine={false}
            tickFormatter={(month) => String(month).slice(0, 3)}
            interval={0}
            angle={-45}
            textAnchor="end"
            height={40}
            tick={{ fontSize: 10 }}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={48}
            tickFormatter={(value) => Number(value).toLocaleString("en-US")}
          />
          <ChartTooltip
            content={
              <ChartTooltipContent
                labelFormatter={(_, payload) => payload[0]?.payload.month}
                formatter={(_, __, item) => (
                  <div className="grid gap-1">
                    <span className="font-medium tabular-nums">
                      Estimate ≈ {formatKwh(item.payload.estimate)}
                    </span>
                    <span className="text-muted-foreground tabular-nums">
                      Likely range {Math.round(item.payload.low).toLocaleString("en-US")}–{formatKwh(item.payload.high)}
                    </span>
                  </div>
                )}
              />
            }
          />
          <Bar dataKey="estimate" fill="var(--color-estimate)" radius={3}>
            <ErrorBar
              dataKey="range"
              stroke="var(--color-range)"
              strokeWidth={1.5}
              width={3}
              isAnimationActive={false}
            />
          </Bar>
        </BarChart>
      </ChartContainer>
      <p className="text-xs text-muted-foreground">
        Typical weather year. Light lines show the annual likely range scaled to each month.
      </p>
    </div>
  )
}
