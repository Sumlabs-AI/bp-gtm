// Types for the FastAPI /leads and /sources endpoints.

// GTM page: Leads keeps only each county's Lead Cells (top Opportunity, /leads/cells);
// Overview shows every home.
export type View = "leads" | "overview"
// GET /leads/cells: every county's Lead Cells, and each county's lowest Opportunity Score among them.
export type LeadCells = { cells: string[]; min_score: Record<string, number> }

export type LeadStatus = "new" | "reviewed" | "qualified" | "excluded"
export type LeadSignal = "solar" | "ev_charger" | "new_home" | "new_owner" | "new_meter" | "pool"
export type BatteryKwh = 25 | 40 | 50
export type BatteryValue = {
  value: number
  ceiling: number
  first_year: number | null
  last_year: number | null
  recent: number
  low: number | null
  low_year: number | null
  high: number | null
  high_year: number | null
}
export type BatteryValues = Record<"25" | "40" | "50", BatteryValue>
export type Consumption = {
  annual_kwh: number
  low_kwh: number
  high_kwh: number
  monthly_kwh: number[]
  peak_summer_kw: number
  peak_winter_kw: number
  electric_heat_prob: number
}

export const BATTERY_SIZES = [25, 40, 50] as const

export const STATUS_LABELS: Record<LeadStatus, string> = {
  new: "Unreviewed",
  reviewed: "Reviewed",
  qualified: "Qualified",
  excluded: "Excluded",
}
export const PRIORITY_HELP = "Fit ÷ 100 × historical grid value for the suggested battery in an average past year (day-ahead plans, no hindsight). Fit is not a purchase probability. Priority value is a ranking metric, not forecast revenue or customer savings."

export function valueBasis(value: BatteryValue | null | undefined): string {
  return value && value.first_year !== null && value.last_year !== null
    ? `Average year ${value.first_year}–${value.last_year}`
    : "Last 12 months"
}

export function formatLeadMoney(value: number): string {
  return `$${Math.round(value).toLocaleString("en-US")}`
}

export function formatKwh(value: number): string {
  return `${Math.round(value).toLocaleString("en-US")} kWh`
}

// What a lead's H3 Cell says about it, read from the Need Engine at request time.
export type CellBlock = {
  baseline_need: number | null
  propensity_score: number | null
  opportunity_score: number | null // Propensity x Baseline Need x Timing (0-100, up to 150 after a storm)
  timing: number // the Timing multiplier in it
  active_alerts: number
  forecast_level: "elevated" | "high" | null
  grid_stress_signals: number
}

export type LeadItem = {
  id: number
  h3_index: string | null
  cell: CellBlock | null // null when the home is outside every seeded Cell
  address: string | null
  city: string | null
  zip: string | null
  county: string
  score: number
  reasons: string
  signals: LeadSignal[]
  triggered_at: string | null
  trigger: string | null
  status: LeadStatus
  load_zone: string | null
  battery_values: BatteryValues | null
  recommended_kwh: BatteryKwh | null
  sizing_reason: string | null
  value: number | null
  expected_value: number | null
  annual_kwh: number | null
}

export type LeadListSummary = {
  leads: number
  avg_baseline_need: number | null
  alert: number
  forecast: number
  grid_stress: number
  grid_state: string | null
}

export type LeadPage = {
  total: number
  items: LeadItem[]
  summary: LeadListSummary
}

export type LeadDriver = {
  key: string
  label: string
  kind: "percentile" | "flag"
  weight: number // 0-1, share of the lead score
  score: number // 0-100
  value: number | boolean | null
}

export type LeadEvidence = {
  type: string
  date: string | null
  source: string
  detail: string
}

export type LeadDetail = LeadItem & {
  drivers: LeadDriver[]
  evidence: LeadEvidence[]
  account: string
  market_value: number | null
  heated_sqft: number | null
  year_built: number | null
  bedrooms: number | null
  full_baths: number | null
  half_baths: number | null
  stories: number | null
  consumption: Consumption | null
  first_seen_at: string
  scored_at: string
  lat: number | null
  lon: number | null
}


export type LeadSummary = {
  properties: number
  leads: number
  new_this_week: number
  by_signal: Record<LeadSignal, number>
  by_zone: Record<string, number>
  last_scored_at: string | null
}

export type SourceStatus = {
  source_id: string
  status: string | null
  started_at: string | null
  finished_at: string | null
  rows: number | null
  inserted: number | null
  updated: number | null
  error: string | null
  last_success_at: string | null
}

export const SIGNAL_LABELS: Record<LeadSignal, string> = {
  solar: "Solar",
  ev_charger: "EV charger",
  new_home: "New home",
  new_owner: "New owner",
  new_meter: "New meter",
  pool: "Pool / spa",
}

export function signalLabel(signal: string): string {
  if (signal === "newly_eligible") return "Newly eligible"
  return SIGNAL_LABELS[signal as LeadSignal] ?? signal
}

export function formatLeadDriverValue(driver: Pick<LeadDriver, "key" | "value">): string {
  if (driver.value === null) return "—"
  if (driver.key === "home_size" && typeof driver.value === "number") {
    return `${Math.round(driver.value).toLocaleString("en-US")} sqft`
  }
  if (driver.key === "home_value" && typeof driver.value === "number") {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    }).format(driver.value)
  }
  if (typeof driver.value === "boolean") return driver.value ? "Yes" : "No"
  return String(driver.value)
}

/** "harris" -> "Harris County" (the appraisal district's spelling varies). */
export function countyName(county: string): string {
  return `${county.charAt(0).toUpperCase()}${county.slice(1)}${county.toLowerCase().endsWith(" county") ? "" : " County"}`
}
