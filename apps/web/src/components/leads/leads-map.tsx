"use client"

import * as React from "react"
import Link from "next/link"
import { setWorkerUrl } from "maplibre-gl"
import Map, { Layer, NavigationControl, Source, type MapLayerMouseEvent, type MapRef } from "react-map-gl/maplibre"
import "maplibre-gl/dist/maplibre-gl.css"

import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { apiFetch } from "@/lib/api"
import { scoreColor } from "@/lib/grid"
import { formatLeadMoney, signalLabel, valueBasis, type LeadDetail, type LeadSignal, type LeadStatus } from "@/lib/leads"
import { cn } from "@/lib/utils"

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
  zone?: string
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

export function LeadsMap({ filters, backHref, className }: { filters: LeadMapFilters; backHref: string; className?: string }) {
  const mapRef = React.useRef<MapRef>(null)
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null)
  const [viewport, setViewport] = React.useState<Viewport | null>(null)
  const [data, setData] = React.useState<LeadGeoResponse | null>(null)
  const [hover, setHover] = React.useState<Hover | null>(null)
  const [error, setError] = React.useState(false)
  const [loading, setLoading] = React.useState(true)
  const [retry, setRetry] = React.useState(0)
  const [selected, setSelected] = React.useState<{ id: number; address?: string | null } | null>(null)
  const [preview, setPreview] = React.useState<{ id: number; lead: LeadDetail | null } | null>(null)
  const [previewRetry, setPreviewRetry] = React.useState(0)

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
    if (filters.zone) params.set("zone", filters.zone)
    if (filters.status) params.set("status", filters.status)

    async function load() {
      setLoading(true)
      try {
        const response = await apiFetch<LeadGeoResponse>(`/leads/geo?${params}`, { signal: controller.signal })
        if (controller.signal.aborted) return
        setData(response)
        setError(false)
        setHover(null)
      } catch {
        if (!controller.signal.aborted) {
          setData(null)
          setError(true)
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    load()
    return () => controller.abort()
  }, [viewport, filters, retry])

  React.useEffect(() => {
    if (!selected) return
    const id = selected.id
    const controller = new AbortController()
    async function loadPreview() {
      try {
        const lead = await apiFetch<LeadDetail>(`/leads/${id}`, { signal: controller.signal })
        if (!controller.signal.aborted) setPreview({ id, lead })
      } catch {
        if (!controller.signal.aborted) setPreview({ id, lead: null })
      }
    }
    loadPreview()
    return () => controller.abort()
  }, [selected, previewRetry])

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
    <div className="flex flex-col gap-3">
      <div className={cn("relative overflow-hidden rounded-xl border", className)} aria-label="Map of Harris County leads">
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
              setSelected({ id: Number(feature.properties.id), address: feature.properties.address })
              setPreview(null)
              setHover(null)
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

        <div role="status" className="absolute top-3 left-3 max-w-[calc(100%-4rem)] rounded-md border bg-background/90 px-3 py-2 text-xs shadow-sm">
          {data ? `${data.total.toLocaleString("en-US")} leads in map view${data.aggregated ? " · grouped" : ""}${loading ? " · Updating…" : ""}` : loading ? "Loading leads…" : "Leads unavailable"}
          {data?.total === 0 && !loading && <p className="mt-1 text-muted-foreground">Move or zoom out to find matching homes.</p>}
        </div>
        {error && (
          <div role="alert" className="absolute top-16 left-3 flex max-w-[calc(100%-1.5rem)] flex-wrap items-center gap-2 rounded-md border bg-background/90 px-3 py-2 text-xs">
            Could not load leads for this view.
            <Button variant="outline" size="sm" disabled={loading} onClick={() => setRetry((value) => value + 1)}>Retry</Button>
          </div>
        )}
        <div className="absolute bottom-7 left-3 flex items-center gap-3 rounded-md border bg-background/90 px-3 py-2 text-xs">
          <span>Color: Fit</span>
          {[0, 50, 100].map((score) => <span key={score} className="flex items-center gap-1"><span className="size-2.5 rounded-full" style={{ background: scoreColor(score) }} />{score}</span>)}
        </div>
        {hover && (
          <div
            className="pointer-events-none absolute hidden w-60 rounded-lg border bg-background p-3 text-xs shadow-md [@media(hover:hover)]:block"
            style={{ left: hover.flip ? hover.x - 252 : hover.x + 12, top: hover.y + 12 }}
          >
            {data?.aggregated ? (
              <>
                <div className="font-medium">{hover.count?.toLocaleString("en-US")} leads · average fit {hover.score.toFixed(0)}</div>
                <div className="mt-1 text-muted-foreground">Zoom in to see homes</div>
              </>
            ) : (
              <>
                <div className="font-medium">{hover.address ?? `Lead ${hover.id}`}</div>
                <div className="mt-1 text-muted-foreground">Fit {hover.score.toFixed(0)} · Latest signal: {hover.trigger ? signalLabel(hover.trigger) : "—"}</div>
              </>
            )}
          </div>
        )}
      {selected && (
        <Card size="sm" className="absolute right-3 bottom-16 left-3 max-w-md" aria-label="Selected lead preview">
          <CardHeader><CardTitle>{preview?.lead?.address ?? selected.address ?? `Lead ${selected.id}`}</CardTitle></CardHeader>
          <CardContent aria-live="polite">
            {preview?.id !== selected.id ? <p className="text-sm text-muted-foreground">Loading lead preview…</p> : preview.lead ? (
              <div className="flex flex-col gap-3">
                <dl className="grid grid-cols-3 gap-3 text-sm">
                  <div><dt className="text-xs text-muted-foreground">Priority value</dt><dd className="font-medium tabular-nums">{preview.lead.expected_value === null ? "Unavailable" : formatLeadMoney(preview.lead.expected_value)}</dd><span className="text-xs text-muted-foreground">Ranking metric</span></div>
                  <div><dt className="text-xs text-muted-foreground">Fit</dt><dd className="font-medium tabular-nums">{preview.lead.score.toFixed(0)} / 100</dd></div>
                  <div><dt className="text-xs text-muted-foreground">Suggested size</dt><dd className="font-medium">{preview.lead.recommended_kwh ? <Badge variant="secondary">{preview.lead.recommended_kwh} kWh</Badge> : "Unavailable"}</dd></div>
                </dl>
                <p className="text-xs text-muted-foreground">Historical grid value to Base · $/year · {valueBasis(Object.values(preview.lead.battery_values ?? {})[0])}. Suggested size is highlighted.</p>
              </div>
            ) : <div className="flex flex-wrap items-center gap-2"><p className="text-sm">Could not load this preview.</p><Button variant="outline" size="sm" onClick={() => { setPreview(null); setPreviewRetry((value) => value + 1) }}>Retry</Button></div>}
          </CardContent>
          <CardFooter className="flex gap-2">
            <Link href={`/leads/${selected.id}?${new URLSearchParams({ back: backHref })}`} className={buttonVariants({ size: "sm" })}>Open lead</Link>
            <Button variant="ghost" size="sm" onClick={() => setSelected(null)}>Close preview</Button>
          </CardFooter>
        </Card>
      )}
      </div>
    </div>
  )
}
