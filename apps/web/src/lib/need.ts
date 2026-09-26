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
  properties: { h3: string; needScore: number | null }
}

export type CellCollection = { type: "FeatureCollection"; features: CellFeature[] }

export type CellDetail = {
  h3: string
  resolution: number
  center: { lat: number; lng: number }
  needScore: number | null
  components: Record<string, unknown>
}
