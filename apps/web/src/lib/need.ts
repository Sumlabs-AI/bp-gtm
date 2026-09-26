// Types for the FastAPI /need endpoints (Need Engine Cells).

// Below this map zoom the Cell layer is hidden and /need/cells isn't called.
export const H3_MAP_MIN_ZOOM = 9

export type Market = { name: string; label: string; center: [number, number] }

export const MARKETS: Market[] = [
  { name: "harris", label: "Houston", center: [-95.37, 29.76] },
  { name: "travis", label: "Austin", center: [-97.74, 30.27] },
]

export type CellFeature = {
  type: "Feature"
  id: string
  geometry: { type: "Polygon"; coordinates: [number, number][][] }
  properties: {
    h3: string
    needScore: number | null
    outageNeed: number | null
    weatherNeed: number | null
    activeAlerts: number
    activeAlertCategory: AlertCategory | null
    activeForecastSignals: number
    forecastLevel: "elevated" | "high" | null
    gridState: string | null
    activeGridStressSignals: number
  }
}

// The ERCOT-wide official condition, given once per map response (also with no Cells).
export type GridSummary = {
  state: string | null
  title: string | null
  eeaLevel: number | null
  official: boolean
  stale: boolean
}

export type CellCollection = { type: "FeatureCollection"; features: CellFeature[]; grid: GridSummary }

export type CellDetail = {
  h3: string
  resolution: number
  center: { lat: number; lng: number }
  loadZone: string | null
  needScore: number | null
  components: { outage?: OutageComponent; weather?: WeatherComponent }
  live: { weather: { alerts: AlertFeed; forecast: ForecastFeed }; grid: LiveGrid }
}

// NWS Alerts: official alerts active for the Cell now. Observed, not scored; never shown
// as equivalent to our derived Forecast Signals.
export type AlertCategory = "tornado" | "tropical" | "severe_storm" | "winter" | "cold" | "heat"

export type NwsAlert = {
  id: string
  event: string
  category: AlertCategory
  severity: string | null
  certainty: string | null
  urgency: string | null
  headline: string | null
  effectiveAt: string
  endsAt: string
  geometrySource: "alert" | "zones"
  firstSeenAt: string
  lastSeenAt: string
}

export type AlertFeed = { fetchedAt: string | null; stale: boolean; signals: NwsAlert[] }

// Outage Need Component: county-level Observed Outage Exposure (EAGLE-I) and Utility
// Reliability Need (EIA-861), each a Texas percentile (0-100, higher = more need).
export type OutageComponent = {
  score: number | null
  observedOutageExposure: null | {
    score: number | null
    county: { fips: string; name: string | null }
    source: string
    dataThrough: string
    yearsObserved: number
    inReferencePopulation: boolean
    modeledCustomers: number
    metrics: {
      hoursPerCustomer5y: number | null
      outageEvents5y: number | null
      majorOutageEvents5y: number | null
      peakPctOut5y: number | null
      hoursPerCustomer365d: number | null
      outageEvents365d: number | null
      majorOutageEvents365d: number | null
      peakPctOut365d: number | null
    }
    percentiles: { hoursPerCustomer5y: number | null }
    lastObservedMajorOutageOn: string | null
    daysSinceLastObservedMajorOutage: number | null
  }
  utilityReliabilityNeed: {
    score: number | null
    utility: { id: number; name: string }
    source: string
    dataThrough: string
    dataThroughYear: number
    yearsUsed: number
    yearly: Record<string, { saidiWithoutMed: number | null; saidiWithMed: number | null }>
    metrics: {
      saidiWithoutMed5y: number | null
      saifiWithoutMed5y: number | null
      saidiWithMed5y: number | null
      saifiWithMed5y: number | null
    }
  } | null
  notes: string[]
}

// Map colouring: which Need Component shades the Cells.
export type ColorBy = "outageNeed" | "weatherNeed"
export const COLOR_BY: { key: ColorBy; label: string }[] = [
  { key: "outageNeed", label: "Outage Need" },
  { key: "weatherNeed", label: "Weather Need" },
]

// Weather Need Component (Baseline): Storm Exposure from the Cell's res-6 parent (~36 km²)
// and Temperature Extremes Exposure from its county, each a Texas percentile.
export type WeatherComponent = {
  score: number | null
  stormExposure: {
    score: number | null
    resolution: number
    sourceCell: string
    source: string
    dataThrough: string
    metrics: {
      warningDays5y: number
      warningDays365d: number
      severeThunderstormWarnings5y: number
      tornadoWarnings5y: number
      extremeWindWarnings5y: number
    }
    percentiles: { warningDays5y: number | null }
    issuingOffice: string | null
    officeNote: string | null
  } | null
  temperatureExtremesExposure: {
    score: number | null
    county: { fips: string; name: string | null }
    source: string
    dataThrough: string
    metrics: {
      heatDays100F5y: number
      heatDays95F5y: number
      coldDays28F5y: number
      coldDays32F5y: number
      heatDays100F365d: number
      heatDays95F365d: number
      coldDays28F365d: number
      coldDays32F365d: number
    }
    percentiles: { heatDays100F5y: number | null; coldDays28F5y: number | null }
    limitations: string[]
  } | null
  notes: string[]
}

// Forecast Signals: OUR reading of NWS grid / SPC outlook data. Not NWS alerts; the UI must
// never present them as equivalent.
export type ForecastSignal = {
  source: "nws_grid" | "spc_outlook"
  condition: "wind" | "heat" | "cold" | "ice" | "severe_storm"
  level: "elevated" | "high"
  comparison: ">=" | "<=" | null
  startAt: string
  endAt: string
  leadHours: number
  peakValue: number | null
  unit: string | null
  threshold: number | null
  label: string | null
  sourceUpdatedAt: string
}

export type SpcFreshness = { fetchedAt: string | null; stale: boolean }
export type GridFreshness = SpcFreshness & { sourceUpdatedAt: string | null }

export type ForecastFeed = {
  resolution: number
  sourceCell: string
  horizonHours: number
  grid: GridFreshness
  spc: SpcFreshness
  signals: ForecastSignal[]
}

// Live grid: the ERCOT Grid Condition (official, as ERCOT declares it) and Grid Stress
// Signals (OUR thresholds on ERCOT data). Never presented as equivalent. No score.
export type LiveGrid = {
  condition: {
    state: string | null
    title: string | null
    eeaLevel: number | null
    prcMw: number | null
    official: boolean
    sourceUpdatedAt: string | null
    fetchedAt: string | null
    stale: boolean
  }
  prices: { loadZone: string | null; latestRt: { price: number; intervalStart: string } | null; stale: boolean }
  stressSignals: {
    type: "low_reserves" | "tight_margin" | "rt_price_spike" | "dam_price_spike"
    category: "reliability" | "market"
    value: number
    threshold: number
    unit: string
    at: string | null
    message: string
    hours: number | null
  }[]
  notes: string[]
}
