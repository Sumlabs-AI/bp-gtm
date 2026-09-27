"use client"

import * as React from "react"
import { ChevronDownIcon, LocateFixedIcon, ZoomInIcon } from "lucide-react"
import { setWorkerUrl, type ExpressionSpecification } from "maplibre-gl"
import Map, { Layer, NavigationControl, Source, type MapLayerMouseEvent, type MapRef } from "react-map-gl/maplibre"
import "maplibre-gl/dist/maplibre-gl.css"

import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { OutageBreakdown } from "@/components/need/outage-breakdown"
import { BaselineNeedBlock } from "@/components/need/baseline-need"
import { ForecastSignals } from "@/components/need/forecast-signals"
import { LiveGridSection } from "@/components/need/live-grid"
import { NwsAlerts } from "@/components/need/nws-alerts"
import { OpportunityBlock } from "@/components/need/opportunity"
import { PropensityBlock } from "@/components/need/propensity"
import { WeatherBreakdown } from "@/components/need/weather-breakdown"
import { apiFetch } from "@/lib/api"
import { scoreColor } from "@/lib/grid"
import { H3_MAP_MIN_ZOOM, MARKETS, type CellCollection, type CellDetail } from "@/lib/need"

const BASEMAP = "https://tiles.openfreemap.org/styles/positron"

// See src/app/maplibre/[file]/route.ts.
if (typeof window !== "undefined") setWorkerUrl("/maplibre/maplibre-gl-worker.mjs")

type Status = "zoom-in" | "loading" | "ready" | "too-many" | "error"
type Hover = {
  x: number
  y: number
  flip: boolean
  h3: string
  liveCategory: string | null
  forecastLevel: string | null
}

export type LeadPoint = {
  type: "Feature"
  geometry: { type: "Point"; coordinates: [number, number] }
  properties: { id: number; address?: string | null }
}

/**
 * The Need map. On its own it explains Cells in a sheet. In controlled mode (the GTM page)
 * it is a filter: it reports the viewport, toggles Cells, dims what's filtered
 * out, and shows the leads inside the filter as points once zoomed in.
 */
export function CellMap({
  className,
  selectedCells,
  onToggleCell,
  onViewport,
  points,
  onPointClick,
  pointsMinZoom = 13,
}: {
  className?: string
  selectedCells?: string[]
  onToggleCell?: (h3: string, additive: boolean) => void
  onViewport?: (bbox: string, zoom: number) => void
  points?: { type: "FeatureCollection"; features: LeadPoint[] } | null
  onPointClick?: (id: number) => void
  pointsMinZoom?: number
}) {
  const controlled = Boolean(onToggleCell)
  const mapRef = React.useRef<MapRef>(null)
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null)
  const [bbox, setBbox] = React.useState<string | null>(null)
  const [data, setData] = React.useState<CellCollection | null>(null)
  const [status, setStatus] = React.useState<Status>("loading")
  const [hover, setHover] = React.useState<Hover | null>(null)
  const [selected, setSelected] = React.useState<string | null>(null)
  const [overPoint, setOverPoint] = React.useState(false)
  const [market, setMarket] = React.useState(MARKETS[0].name)
  // Keyed by Cell so a stale detail never shows under a newly selected Cell.
  const [detail, setDetail] = React.useState<CellDetail | null>(null)
  const shownDetail = detail?.h3 === selected ? detail : null

  function readViewport() {
    const map = mapRef.current
    if (!map) return
    const b = map.getBounds()
    const box = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((v) => v.toFixed(5)).join(",")
    // The list follows the viewport at every zoom; only the Cells wait for the minimum.
    onViewport?.(box, map.getZoom())
    if (map.getZoom() < H3_MAP_MIN_ZOOM) {
      setBbox(null)
      setData(null)
      setStatus("zoom-in")
      return
    }
    setStatus("loading")
    setBbox(box)
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
    const feature = e.features?.[0]
    setOverPoint(feature?.layer?.id === "lead-points")
    const properties = feature?.properties
    setHover(
      properties?.h3
        ? {
            x: e.point.x,
            y: e.point.y,
            flip: e.point.x > e.target.getContainer().clientWidth - 220,
            h3: properties.h3,
            liveCategory: properties.activeAlertCategory ?? null,
            forecastLevel: properties.forecastLevel ?? null,
          }
        : null
    )
  }

  const highlighted = [...(controlled ? (selectedCells ?? []) : [selected ?? ""]), hover?.h3 ?? ""]
  // Clicked Cells narrow the list to themselves, so the others dim too.
  const focus: ExpressionSpecification[] =
    controlled && selectedCells?.length
      ? [["in", ["get", "h3"], ["literal", selectedCells]] as ExpressionSpecification]
      : []
  const inFocus: ExpressionSpecification | null = focus.length ? (["all", ...focus] as ExpressionSpecification) : null

  return (
    <div className={className}>
      <div className="relative h-full overflow-hidden rounded-xl border">
        <Map
          ref={mapRef}
          initialViewState={{ longitude: MARKETS[0].center[0], latitude: MARKETS[0].center[1], zoom: 10 }}
          mapStyle={BASEMAP}
          interactiveLayerIds={[...(data ? ["cells-fill"] : []), ...(points ? ["lead-points"] : [])]}
          onLoad={readViewport}
          onMoveEnd={() => {
            if (timer.current) clearTimeout(timer.current)
            timer.current = setTimeout(readViewport, 300)
          }}
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
          onClick={(e) => {
            const feature = e.features?.[0]
            if (feature?.layer?.id === "lead-points" && onPointClick) {
              onPointClick(Number(feature.properties?.id))
              return
            }
            const h3 = feature?.properties?.h3 ?? null
            if (controlled) {
              if (h3) onToggleCell?.(h3, e.originalEvent.shiftKey || e.originalEvent.metaKey)
            } else {
              setSelected(h3)
            }
          }}
          cursor={hover || overPoint ? "pointer" : "grab"}
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
                    // Opportunity when known, else the neutral substrate tint.
                    "fill-color": [
                      "case",
                      ["==", ["get", "opportunityScore"], null],
                      "#1e4d2b",
                      ["interpolate", ["linear"], ["get", "opportunityScore"], 0, scoreColor(0), 50, scoreColor(50), 100, scoreColor(100)],
                    ],
                    // Filtered out (Cell not selected): dimmed so the filter is visible.
                    "fill-opacity": [
                      "case",
                      ["==", ["get", "opportunityScore"], null],
                      0.08,
                      inFocus ? ["case", inFocus, 0.45, 0.06] : 0.45,
                    ],
                  }}
                />,
                <Layer
                  key="cells-line"
                  id="cells-line"
                  minzoom={H3_MAP_MIN_ZOOM}
                  type="line"
                  paint={{ "line-color": "#1e4d2b", "line-width": 0.5, "line-opacity": 0.35 }}
                />,
                <Layer
                  key="cells-forecast"
                  id="cells-forecast"
                  minzoom={H3_MAP_MIN_ZOOM}
                  type="line"
                  // Forecast Signals (our reading of NWS/SPC data): dashed amber, never the
                  // solid red used for official NWS alerts.
                  filter={[">", ["get", "activeForecastSignals"], 0]}
                  paint={{ "line-color": "#f59e0b", "line-width": 1.5, "line-dasharray": [2, 2] }}
                />,
                <Layer
                  key="cells-alert"
                  id="cells-alert"
                  minzoom={H3_MAP_MIN_ZOOM}
                  type="line"
                  // Cells under an active NWS alert: outlined, not coloured (no live score yet).
                  filter={[">", ["get", "activeAlerts"], 0]}
                  paint={{ "line-color": "#dc2626", "line-width": 1.5 }}
                />,
                <Layer
                  key="cells-highlight"
                  id="cells-highlight"
                  minzoom={H3_MAP_MIN_ZOOM}
                  type="line"
                  filter={["in", ["get", "h3"], ["literal", highlighted]]}
                  paint={{ "line-color": "#102a17", "line-width": 2.5 }}
                />,
              ]}
            </Source>
          )}
          {points && (
            <Source id="leads" type="geojson" data={points}>
              <Layer
                id="lead-points"
                source="leads"
                type="circle"
                minzoom={pointsMinZoom}
                paint={{
                  "circle-color": "#0f172a",
                  "circle-radius": 4,
                  "circle-stroke-color": "#ffffff",
                  "circle-stroke-width": 1,
                }}
              />
            </Source>
          )}
          <NavigationControl position="top-right" showCompass={false} />
        </Map>

        <div className="absolute top-3 left-3 flex items-center gap-2 rounded-md border bg-background/90 px-2 py-1.5 text-xs shadow-sm">
          {/* A menu, not a <select>: picking the current market again still flies back to it. */}
          <DropdownMenu>
            <DropdownMenuTrigger render={<Button size="sm" variant="ghost" className="font-medium" title="Go to a market" />}>
              <LocateFixedIcon />
              {MARKETS.find((m) => m.name === market)?.label}
              <ChevronDownIcon className="opacity-60" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {MARKETS.map((m) => (
                <DropdownMenuItem
                  key={m.name}
                  onClick={() => {
                    setMarket(m.name)
                    mapRef.current?.flyTo({ center: m.center, zoom: 10 })
                  }}
                >
                  {m.label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        {(status === "zoom-in" || status === "too-many") && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <div className="flex items-center gap-2 rounded-lg border bg-background/95 px-4 py-2.5 text-sm font-medium shadow-md">
              <ZoomInIcon className="size-4 text-muted-foreground" />
              Zoom in to see Cells
            </div>
          </div>
        )}

        <div className="absolute bottom-3 left-3 flex flex-col items-start gap-1">
        {/* Secondary info: the Cell count stays out of the way; problems still read clearly. */}
        <span
          className={`rounded bg-background/80 px-1.5 py-0.5 text-[11px] ${
            status === "ready" || status === "loading" ? "text-muted-foreground" : "font-medium text-foreground"
          }`}
        >
          {STATUS_TEXT[status](data?.features.length ?? 0)}
        </span>
        </div>

        {hover && (
          <div
            className="pointer-events-none absolute z-10 rounded-lg border bg-background p-2 font-mono text-xs shadow-md"
            style={{ left: hover.flip ? hover.x - 180 : hover.x + 12, top: hover.y + 12 }}
          >
            {hover.h3}
            {hover.liveCategory && (
              <div className="mt-1 font-sans text-red-600">Official NWS alert: {hover.liveCategory.replace("_", " ")}</div>
            )}
            {hover.forecastLevel && (
              <div className="mt-1 font-sans text-amber-600">Forecast ({hover.forecastLevel}), our reading of NWS data</div>
            )}
          </div>
        )}
      </div>

      {!controlled && (
      <Sheet open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle className="font-mono">{selected}</SheetTitle>
            <SheetDescription>H3 Cell. Opportunity first, then Baseline Need, Propensity, live signals and the component details.</SheetDescription>
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
            <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto pb-4">
              <OpportunityBlock opportunity={shownDetail.opportunity} timing={shownDetail.timing} />
              {shownDetail.baseline && <BaselineNeedBlock baseline={shownDetail.baseline} />}
              <PropensityBlock propensity={shownDetail.propensity} />
              <NwsAlerts feed={shownDetail.live.weather.alerts} />
              <ForecastSignals feed={shownDetail.live.weather.forecast} />
              <LiveGridSection grid={shownDetail.live.grid} />
              {shownDetail.components.outage && <OutageBreakdown outage={shownDetail.components.outage} />}
              {shownDetail.components.weather && <WeatherBreakdown weather={shownDetail.components.weather} />}
            </div>
          )}
        </SheetContent>
      </Sheet>
      )}
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
