"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { setWorkerUrl } from "maplibre-gl"
import Map, { Layer, NavigationControl, Source, type MapLayerMouseEvent, type MapRef } from "react-map-gl/maplibre"
import "maplibre-gl/dist/maplibre-gl.css"

import { apiFetch } from "@/lib/api"
import { scoreColor } from "@/lib/grid"
import { signalLabel, type LeadSignal, type LeadStatus } from "@/lib/leads"

const BASEMAP = "https://tiles.openfreemap.org/styles/positron"
const HARRIS_BOUNDS: [[number, number], [number, number]] = [
  [-95.97, 29.49],
  [-94.90, 30.18],
]

// See src/app/maplibre/[file]/route.ts.
if (typeof window !== "undefined") setWorkerUrl("/maplibre/maplibre-gl-worker.mjs")

type LeadMapFilters = {
  minScore: number
  signals: LeadSignal[]
  newOnly: boolean
  zip: string
  status?: LeadStatus
}

type LeadGeoResponse = {
  type: "FeatureCollection"
  aggregated: boolean
  total: number
  features: {
    type: "Feature"
    geometry: { type: "Point"; coordinates: [number, number] }
    properties: {
      id?: number
      count?: number
      score: number
      address?: string | null
      trigger?: string | null
    }
  }[]
}

type Viewport = { bbox: string; zoom: number }
type Hover = {
  x: number
  y: number
  flip: boolean
  score: number
  id?: number
  count?: number
  address?: string | null
  trigger?: string | null
}

export function LeadsMap({ filters, className }: { filters: LeadMapFilters; className?: string }) {
  const router = useRouter()
  const mapRef = React.useRef<MapRef>(null)
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null)
  const [viewport, setViewport] = React.useState<Viewport | null>(null)
  const [data, setData] = React.useState<LeadGeoResponse | null>(null)
  const [hover, setHover] = React.useState<Hover | null>(null)
  const [error, setError] = React.useState(false)

  function readViewport() {
    const map = mapRef.current
    if (!map) return
    const bounds = map.getBounds()
    const next = {
      bbox: [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].join(","),
      zoom: Math.round(map.getZoom()),
    }
    setViewport((previous) => previous?.bbox === next.bbox && previous.zoom === next.zoom ? previous : next)
  }

  React.useEffect(() => {
    if (!viewport) return
    const controller = new AbortController()
    const params = new URLSearchParams({ bbox: viewport.bbox, zoom: String(viewport.zoom) })
    if (filters.minScore) params.set("min_score", String(filters.minScore))
    filters.signals.forEach((signal) => params.append("signals", signal))
    if (filters.newOnly) params.set("new_only", "true")
    if (filters.zip) params.set("zip", filters.zip)
    if (filters.status) params.set("status", filters.status)

    async function load() {
      try {
        const response = await apiFetch<LeadGeoResponse>(`/leads/geo?${params}`, { signal: controller.signal })
        setData(response)
        setError(false)
        setHover(null)
      } catch {
        if (!controller.signal.aborted) {
          setData(null)
          setError(true)
        }
      }
    }
    load()
    return () => controller.abort()
  }, [viewport, filters])

  React.useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])

  function onMove(e: MapLayerMouseEvent) {
    const properties = e.features?.[0]?.properties
    if (!properties) {
      setHover(null)
      return
    }
    setHover({
      x: e.point.x,
      y: e.point.y,
      flip: e.point.x > e.target.getContainer().clientWidth - 260,
      score: Number(properties.score),
      id: properties.id,
      count: properties.count,
      address: properties.address,
      trigger: properties.trigger,
    })
  }

  return (
    <div className={className}>
      <div className="relative h-full overflow-hidden rounded-xl border">
        <Map
          ref={mapRef}
          initialViewState={{ bounds: HARRIS_BOUNDS, fitBoundsOptions: { padding: 24 } }}
          mapStyle={BASEMAP}
          interactiveLayerIds={data ? [data.aggregated ? "lead-cells" : "lead-points"] : []}
          onLoad={readViewport}
          onMoveEnd={() => {
            if (timer.current) clearTimeout(timer.current)
            timer.current = setTimeout(readViewport, 300)
          }}
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
          onClick={(e) => {
            const feature = e.features?.[0]
            if (!feature) return
            if (data?.aggregated && feature.geometry.type === "Point") {
              e.target.easeTo({ center: feature.geometry.coordinates as [number, number], zoom: e.target.getZoom() + 2 })
            } else if (feature.properties?.id) {
              router.push(`/leads/${feature.properties.id}`)
            }
          }}
          cursor={hover ? "pointer" : "grab"}
          scrollZoom={false}
          attributionControl={{ compact: true }}
        >
          {data && (
            <Source id="leads" type="geojson" data={data}>
              {data.aggregated ? (
                // An array, not a Fragment: <Source> only passes `source` to direct children.
                [
                  <Layer
                    key="lead-cells"
                    id="lead-cells"
                    source="leads"
                    type="circle"
                    paint={{
                      "circle-color": ["interpolate", ["linear"], ["get", "score"], 0, scoreColor(0), 50, scoreColor(50), 100, scoreColor(100)],
                      // Cells are ~1/8 of a tile wide, so keep circles small enough not to overlap.
                      "circle-radius": ["interpolate", ["linear"], ["get", "count"], 1, 6, 100, 9, 1000, 13, 10000, 18],
                      "circle-stroke-color": "#ffffff",
                      "circle-stroke-width": 1.5,
                    }}
                  />,
                  <Layer
                    key="lead-counts"
                    id="lead-counts"
                    source="leads"
                    type="symbol"
                    layout={{ "text-field": ["to-string", ["get", "count"]], "text-font": ["Noto Sans Regular"], "text-size": 10, "text-allow-overlap": false }}
                    paint={{ "text-color": "#ffffff", "text-halo-color": "#334155", "text-halo-width": 1 }}
                  />,
                ]
              ) : (
                <Layer
                  id="lead-points"
                    source="leads"
                  type="circle"
                  paint={{
                    "circle-color": ["interpolate", ["linear"], ["get", "score"], 0, scoreColor(0), 50, scoreColor(50), 100, scoreColor(100)],
                    "circle-radius": 5,
                    "circle-stroke-color": "#ffffff",
                    "circle-stroke-width": 1.5,
                  }}
                />
              )}
            </Source>
          )}
          <NavigationControl position="top-right" showCompass={false} />
        </Map>

        <div className="absolute top-3 left-3 rounded-md border bg-background/90 px-3 py-2 text-xs shadow-sm">
          {data ? `${data.total.toLocaleString("en-US")} leads in view${data.aggregated ? " · grouped" : ""}` : error ? "Leads unavailable" : "Loading leads…"}
        </div>
        {error && (
          <div className="absolute bottom-3 left-3 rounded-md border bg-background/90 px-3 py-2 text-xs text-muted-foreground">
            Could not load leads for this view.
          </div>
        )}
        {hover && (
          <div
            className="pointer-events-none absolute z-10 w-60 rounded-lg border bg-background p-3 text-xs shadow-md"
            style={{ left: hover.flip ? hover.x - 252 : hover.x + 12, top: hover.y + 12 }}
          >
            {data?.aggregated ? (
              <>
                <div className="font-medium">{hover.count?.toLocaleString("en-US")} leads · avg score {hover.score.toFixed(0)}</div>
                <div className="mt-1 text-muted-foreground">Zoom in to see homes</div>
              </>
            ) : (
              <>
                <div className="font-medium">{hover.address ?? `Lead ${hover.id}`}</div>
                <div className="mt-1 text-muted-foreground">Score {hover.score.toFixed(0)} · Trigger: {hover.trigger ? signalLabel(hover.trigger) : "—"}</div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
