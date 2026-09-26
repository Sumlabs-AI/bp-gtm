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
  properties: { h3: string; needScore: number | null; outageNeed: number | null }
}

export type CellCollection = { type: "FeatureCollection"; features: CellFeature[] }

export type CellDetail = {
  h3: string
  resolution: number
  center: { lat: number; lng: number }
  loadZone: string | null
  needScore: number | null
  components: { outage?: OutageComponent }
}

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
