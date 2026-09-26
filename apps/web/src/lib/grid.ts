// Types for the FastAPI /grid endpoints (see apps/api/app/routers/grid.py).

export type Driver = {
  key: string
  label: string
  unit: string
  weight: number // 0-1, share of the Grid Value Score
  score: number // 0-100, relative to the other load zones
  value: number // raw metric in `unit`
  explanation: string
}

export type ZoneSummary = {
  code: string
  name: string
  description: string
  on_map: boolean
  rank: number
  grid_value_score: number
  primary_reason: string
  drivers: Driver[]
}

export type ZoneDetail = ZoneSummary & {
  period_start: string
  period_end: string
  metrics: Record<string, number>
  series: {
    hourly_profile: { hour: number; zone: number; hub: number }[]
    monthly: { month: string; arbitrage_usd: number; avg_basis: number }[]
  }
  assumptions: {
    battery: { capacity_kwh: number; power_kw: number; round_trip_efficiency: number }
    scoring: { lookback_days: number; scarcity_threshold: number; spread_hours: number }
  }
}

// Sequential scale for "how much Base should want capacity here" (0 = least, 100 = most).
const STOPS: [number, [number, number, number]][] = [
  [0, [226, 232, 240]],
  [50, [134, 200, 150]],
  [100, [21, 128, 61]],
]

export function scoreColor(score: number): string {
  const s = Math.max(0, Math.min(100, score))
  const i = s <= 50 ? 0 : 1
  const [s0, c0] = STOPS[i]
  const [s1, c1] = STOPS[i + 1]
  const t = (s - s0) / (s1 - s0)
  const [r, g, b] = c0.map((c, k) => Math.round(c + (c1[k] - c) * t))
  return `rgb(${r}, ${g}, ${b})`
}

export function formatDriverValue(d: Pick<Driver, "value" | "unit">): string {
  switch (d.unit) {
    case "$/battery/yr":
      return `$${Math.round(d.value).toLocaleString("en-US")}/yr`
    case "$/MWh":
      return `$${d.value.toFixed(2)}/MWh`
    case "h/yr":
      return `${d.value.toFixed(1)} h/yr`
    case "% of intervals":
      return `${d.value.toFixed(1)}%`
    default:
      return `${d.value}`
  }
}
