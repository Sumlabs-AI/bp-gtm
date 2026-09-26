"use client"

import * as React from "react"
import { setWorkerUrl } from "maplibre-gl"
import Map, { Layer, NavigationControl, Source, type MapLayerMouseEvent, type MapRef } from "react-map-gl/maplibre"
import "maplibre-gl/dist/maplibre-gl.css"

import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { OutageBreakdown } from "@/components/need/outage-breakdown"
import { LiveWeatherSignals } from "@/components/need/live-weather"
import { WeatherBreakdown } from "@/components/need/weather-breakdown"
import { apiFetch } from "@/lib/api"
import { scoreColor } from "@/lib/grid"
import { COLOR_BY, H3_MAP_MIN_ZOOM, MARKETS, type CellCollection, type CellDetail, type ColorBy } from "@/lib/need"

const BASEMAP = "https://tiles.openfreemap.org/styles/positron"

// See src/app/maplibre/[file]/route.ts.
if (typeof window !== "undefined") setWorkerUrl("/maplibre/maplibre-gl-worker.mjs")

type Status = "zoom-in" | "loading" | "ready" | "too-many" | "error"
type Hover = { x: number; y: number; flip: boolean; h3: string; liveCategory: string | null }

export function CellMap({ className }: { className?: string }) {
  const mapRef = React.useRef<MapRef>(null)
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null)
  const [bbox, setBbox] = React.useState<string | null>(null)
  const [data, setData] = React.useState<CellCollection | null>(null)
  const [status, setStatus] = React.useState<Status>("loading")
  const [hover, setHover] = React.useState<Hover | null>(null)
  const [colorBy, setColorBy] = React.useState<ColorBy>("outageNeed")
  const [selected, setSelected] = React.useState<string | null>(null)
  // Keyed by Cell so a stale detail never shows under a newly selected Cell.
  const [detail, setDetail] = React.useState<CellDetail | null>(null)
  const shownDetail = detail?.h3 === selected ? detail : null

  function readViewport() {
    const map = mapRef.current
    if (!map) return
    if (map.getZoom() < H3_MAP_MIN_ZOOM) {
      setBbox(null)
      setData(null)
      setStatus("zoom-in")
      return
    }
    const b = map.getBounds()
    setStatus("loading")
    setBbox([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((v) => v.toFixed(5)).join(","))
  }

  React.useEffect(() => {
    if (!bbox) return
    const controller = new AbortController()
    apiFetch<CellCollection>(`/need/cells?bbox=${bbox}`, { signal: controller.signal })
      .then((response) => {
        setData(response)
        setStatus("ready")
      })
      .catch((error: Error) => {
        if (controller.signal.aborted) return
        setData(null)
        setStatus(error.message.startsWith("API 400") ? "too-many" : "error")
      })
    return () => controller.abort()
  }, [bbox])

  React.useEffect(() => {
    if (!selected) return
    const controller = new AbortController()
    apiFetch<CellDetail>(`/need/cells/${selected}`, { signal: controller.signal })
      .then(setDetail)
      .catch(() => {})
    return () => controller.abort()
  }, [selected])

  React.useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])

  function onMove(e: MapLayerMouseEvent) {
    const properties = e.features?.[0]?.properties
    setHover(
      properties?.h3
        ? {
            x: e.point.x,
            y: e.point.y,
            flip: e.point.x > e.target.getContainer().clientWidth - 220,
            h3: properties.h3,
            liveCategory: properties.activeWeatherCategory ?? null,
          }
        : null
    )
  }

  const highlighted = [selected ?? "", hover?.h3 ?? ""]

  return (
    <div className={className}>
      <div className="relative h-full overflow-hidden rounded-xl border">
        <Map
          ref={mapRef}
          initialViewState={{ longitude: MARKETS[0].center[0], latitude: MARKETS[0].center[1], zoom: 10 }}
          mapStyle={BASEMAP}
          interactiveLayerIds={data ? ["cells-fill"] : []}
          onLoad={readViewport}
          onMoveEnd={() => {
            if (timer.current) clearTimeout(timer.current)
            timer.current = setTimeout(readViewport, 300)
          }}
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
          onClick={(e) => setSelected(e.features?.[0]?.properties?.h3 ?? null)}
          cursor={hover ? "pointer" : "grab"}
          attributionControl={{ compact: true }}
        >
          {data && (
            <Source id="cells" type="geojson" data={data}>
              {/* An array, not a Fragment: <Source> only passes `source` to direct children. */}
              {[
                <Layer
                  key="cells-fill"
                  id="cells-fill"
                  minzoom={H3_MAP_MIN_ZOOM}
                  type="fill"
                  paint={{
                    // The selected Need Component when known, else the neutral substrate tint.
                    "fill-color": [
                      "case",
                      ["==", ["get", colorBy], null],
                      "#6366f1",
                      ["interpolate", ["linear"], ["get", colorBy], 0, scoreColor(0), 50, scoreColor(50), 100, scoreColor(100)],
                    ],
                    "fill-opacity": ["case", ["==", ["get", colorBy], null], 0.08, 0.45],
                  }}
                />,
                <Layer
                  key="cells-line"
                  id="cells-line"
                  minzoom={H3_MAP_MIN_ZOOM}
                  type="line"
                  paint={{ "line-color": "#6366f1", "line-width": 0.5, "line-opacity": 0.5 }}
                />,
                <Layer
                  key="cells-live"
                  id="cells-live"
                  minzoom={H3_MAP_MIN_ZOOM}
                  type="line"
                  // Cells under an active NWS alert: outlined, not coloured (no live score yet).
                  filter={[">", ["get", "activeWeatherSignals"], 0]}
                  paint={{ "line-color": "#dc2626", "line-width": 1.5 }}
                />,
                <Layer
                  key="cells-highlight"
                  id="cells-highlight"
                  minzoom={H3_MAP_MIN_ZOOM}
                  type="line"
                  filter={["in", ["get", "h3"], ["literal", highlighted]]}
                  paint={{ "line-color": "#312e81", "line-width": 2.5 }}
                />,
              ]}
            </Source>
          )}
          <NavigationControl position="top-right" showCompass={false} />
        </Map>

        <div className="absolute top-3 left-3 flex items-center gap-2 rounded-md border bg-background/90 px-2 py-1.5 text-xs shadow-sm">
          {MARKETS.map((m) => (
            <Button
              key={m.name}
              size="sm"
              variant="ghost"
              onClick={() => mapRef.current?.flyTo({ center: m.center, zoom: 10 })}
            >
              {m.label}
            </Button>
          ))}
          <span className="pr-1 text-muted-foreground">{STATUS_TEXT[status](data?.features.length ?? 0)}</span>
        </div>

        <div className="absolute top-3 right-12 flex items-center gap-1 rounded-md border bg-background/90 px-2 py-1.5 text-xs shadow-sm">
          <span className="pr-1 text-muted-foreground">Colour by</span>
          {COLOR_BY.map((c) => (
            <Button key={c.key} size="sm" variant={colorBy === c.key ? "secondary" : "ghost"} onClick={() => setColorBy(c.key)}>
              {c.label}
            </Button>
          ))}
        </div>

        {hover && (
          <div
            className="pointer-events-none absolute z-10 rounded-lg border bg-background p-2 font-mono text-xs shadow-md"
            style={{ left: hover.flip ? hover.x - 180 : hover.x + 12, top: hover.y + 12 }}
          >
            {hover.h3}
            {hover.liveCategory && (
              <div className="mt-1 font-sans text-red-600">Active NWS alert: {hover.liveCategory.replace("_", " ")}</div>
            )}
          </div>
        )}
      </div>

      <Sheet open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle className="font-mono">{selected}</SheetTitle>
            <SheetDescription>H3 Cell. The combined Need Score arrives once more Need Components exist.</SheetDescription>
          </SheetHeader>
          {shownDetail && (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 px-4 text-sm">
              <dt className="text-muted-foreground">Resolution</dt>
              <dd className="tabular-nums">{shownDetail.resolution}</dd>
              <dt className="text-muted-foreground">Center</dt>
              <dd className="tabular-nums">
                {shownDetail.center.lat.toFixed(5)}, {shownDetail.center.lng.toFixed(5)}
              </dd>
              <dt className="text-muted-foreground">Load Zone</dt>
              <dd className="font-mono">{shownDetail.loadZone ?? "Unknown"}</dd>
              <dt className="text-muted-foreground">Need Score</dt>
              <dd>{shownDetail.needScore ?? "—"}</dd>
            </dl>
          )}
          {shownDetail && (
            <div className="flex flex-col gap-6 overflow-y-auto pb-4">
              <LiveWeatherSignals live={shownDetail.live.weather} />
              {shownDetail.components.outage && <OutageBreakdown outage={shownDetail.components.outage} />}
              {shownDetail.components.weather && <WeatherBreakdown weather={shownDetail.components.weather} />}
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}

const STATUS_TEXT: Record<Status, (n: number) => string> = {
  "zoom-in": () => "Zoom in to see Cells",
  loading: () => "Loading Cells…",
  ready: (n) => `${n.toLocaleString("en-US")} Cells in view`,
  "too-many": () => "Too many Cells in view. Zoom in.",
  error: () => "Could not load Cells",
}
