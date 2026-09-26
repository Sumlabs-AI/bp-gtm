// Types for the FastAPI /leads and /sources endpoints.

export type LeadStatus = "new" | "reviewed" | "qualified" | "excluded"
export type LeadSignal = "solar" | "ev_charger" | "new_home" | "new_owner" | "new_meter" | "pool"
export type BatteryKwh = 25 | 40 | 50
export type BatteryValues = Record<"25" | "40" | "50", number>

export type LeadItem = {
  id: number
  address: string | null
  city: string | null
  zip: string | null
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
}

export type LeadPage = {
  total: number
  items: LeadItem[]
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
  county: string
  account: string
  market_value: number | null
  heated_sqft: number | null
  year_built: number | null
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
