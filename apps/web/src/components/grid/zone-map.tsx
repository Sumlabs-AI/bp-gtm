"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { setWorkerUrl } from "maplibre-gl"
import Map, { Layer, NavigationControl, Source, type MapLayerMouseEvent } from "react-map-gl/maplibre"
import "maplibre-gl/dist/maplibre-gl.css"

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { formatDriverValue, scoreColor, type ZoneSummary } from "@/lib/grid"

const BASEMAP = "https://tiles.openfreemap.org/styles/positron"
const TEXAS_BOUNDS: [[number, number], [number, number]] = [
  [-106.7, 25.8],
  [-93.5, 36.6],
]

// See src/app/maplibre/[file]/route.ts.
if (typeof window !== "undefined") setWorkerUrl("/maplibre/maplibre-gl-worker.mjs")

type Hover = { code: string; x: number; y: number; flip: boolean }

export function ZoneMap({
  zones,
  selected,
  className,
}: {
  zones: ZoneSummary[] // all ranked zones; ones without geometry just aren't drawn
  selected?: string
  className?: string
}) {
  const router = useRouter()
  const [colorBy, setColorBy] = React.useState("grid_value")
  const [hover, setHover] = React.useState<Hover | null>(null)
  const byCode = React.useMemo(() => Object.fromEntries(zones.map((z) => [z.code, z])), [zones])

  const scoreOf = React.useCallback(
    (z: ZoneSummary) =>
      colorBy === "grid_value"
        ? z.grid_value_score
        : (z.drivers.find((d) => d.key === colorBy)?.score ?? 0),
    [colorBy]
  )

  // MapLibre "match" expression: zone code -> fill color.
  const fillColor = React.useMemo(
    () =>
      [
        "match",
        ["get", "code"],
        ...zones.flatMap((z) => [z.code, scoreColor(scoreOf(z))]),
        "#cccccc",
      ] as unknown as string,
    [zones, scoreOf]
  )

  const options = [
    { value: "grid_value", label: "Grid Value Score" },
    ...(zones[0]?.drivers ?? []).map((d) => ({ value: d.key, label: d.label })),
  ]

  function onMove(e: MapLayerMouseEvent) {
    const code = e.features?.[0]?.properties?.code as string | undefined
    // Flip the tooltip to the left of the cursor near the right edge.
    const flip = e.point.x > e.target.getContainer().clientWidth - 260
    setHover(code ? { code, x: e.point.x, y: e.point.y, flip } : null)
  }

  const hovered = hover ? byCode[hover.code] : undefined
  const hoveredDriver = hovered?.drivers.find((d) => d.key === colorBy)

  return (
    <div className={className}>
      <div className="relative h-full overflow-hidden rounded-xl border">
        <Map
          initialViewState={{ bounds: TEXAS_BOUNDS, fitBoundsOptions: { padding: 24 } }}
          mapStyle={BASEMAP}
          interactiveLayerIds={["zones-fill"]}
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
          onClick={(e) => {
            const code = e.features?.[0]?.properties?.code
            if (code) router.push(`/grid/${code}`)
          }}
          cursor={hover ? "pointer" : "grab"}
          scrollZoom={false} // let the wheel scroll the page; zoom with the buttons
          attributionControl={{ compact: true }}
        >
          <Source id="zones" type="geojson" data="/geo/ercot-zones.geojson">
            <Layer
              id="zones-fill"
              type="fill"
              paint={{ "fill-color": fillColor, "fill-opacity": 0.75 }}
            />
            <Layer
              id="zones-line"
              type="line"
              paint={{ "line-color": "#334155", "line-width": 0.8, "line-opacity": 0.6 }}
            />
            <Layer
              id="zones-selected"
              type="line"
              filter={["in", ["get", "code"], ["literal", [selected ?? "", hover?.code ?? ""]]]}
              paint={{ "line-color": "#0f172a", "line-width": 2.5 }}
            />
          </Source>
          <NavigationControl position="top-right" showCompass={false} />
        </Map>

        <div className="absolute top-3 left-3">
          <Select
            items={options}
            value={colorBy}
            onValueChange={(v) => v !== null && setColorBy(v)}
          >
            <SelectTrigger size="sm" className="w-48 bg-background" aria-label="Color zones by">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {options.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <Legend />

        {hovered && hover && (
          <div
            className="pointer-events-none absolute z-10 w-60 rounded-lg border bg-background p-3 text-xs shadow-md"
            style={{ left: hover.flip ? hover.x - 252 : hover.x + 12, top: hover.y + 12 }}
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-sm font-medium">{hovered.name}</span>
              <span className="font-mono text-muted-foreground">{hovered.code}</span>
            </div>
            <div className="mt-1 text-muted-foreground">
              Grid Value <span className="font-medium text-foreground">{hovered.grid_value_score.toFixed(0)}</span>
              {" · "}Rank {hovered.rank} of {zones.length}
            </div>
            {hoveredDriver && (
              <div className="mt-1 text-muted-foreground">
                {hoveredDriver.label}:{" "}
                <span className="font-medium text-foreground">{formatDriverValue(hoveredDriver)}</span>
              </div>
            )}
            <div className="mt-2">{hovered.primary_reason}</div>
          </div>
        )}
      </div>
    </div>
  )
}

function Legend() {
  return (
    <div className="absolute bottom-3 left-3 rounded-md border bg-background/90 px-3 py-2 text-xs">
      <div
        className="h-2 w-40 rounded-full"
        style={{
          background: `linear-gradient(to right, ${[0, 25, 50, 75, 100].map(scoreColor).join(", ")})`,
        }}
      />
      <div className="mt-1 flex justify-between text-muted-foreground">
        <span>Lower value</span>
        <span>Higher value</span>
      </div>
    </div>
  )
}
