"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { setWorkerUrl } from "maplibre-gl"
import Map, { Layer, NavigationControl, Source, type MapLayerMouseEvent } from "react-map-gl/maplibre"
import "maplibre-gl/dist/maplibre-gl.css"

import { averageGridValue, formatDriverValue, scoreColor, type ZoneSummary } from "@/lib/grid"
import { formatLeadMoney, valueBasis } from "@/lib/leads"
import { cn } from "@/lib/utils"

const BASEMAP = "https://tiles.openfreemap.org/styles/positron"
const ZONES_URL = `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/grid/zones.geojson`
const TEXAS_BOUNDS: [[number, number], [number, number]] = [
  [-106.7, 25.8],
  [-93.5, 36.6],
]

// See src/app/maplibre/[file]/route.ts.
if (typeof window !== "undefined") setWorkerUrl("/maplibre/maplibre-gl-worker.mjs")

const NO_HISTORY_COLOR = "#cccccc"

type Hover = { code: string; x: number; y: number }

export function ZoneMap({
  zones,
  selected,
  metric = "average",
  className,
}: {
  zones: ZoneSummary[] // Include zones without geometry so the legend uses the same scale.
  selected?: string
  metric?: string
  className?: string
}) {
  const router = useRouter()
  const [hover, setHover] = React.useState<Hover | null>(null)
  const byCode = React.useMemo(() => Object.fromEntries(zones.map((z) => [z.code, z])), [zones])
  const dollarMax = Math.max(250, Math.ceil(Math.max(0, ...zones.map((zone) => averageGridValue(zone) ?? 0)) / 250) * 250)
  const driver = zones.flatMap((zone) => zone.drivers).find((item) => item.key === metric)
  const metricLabel = metric === "average"
    ? "40 kWh · Average year · $/yr"
    : metric === "grid_value"
      ? "Zone Economics Score"
      : (driver?.label ?? "Price analysis")

  const scoreOf = React.useCallback(
    (zone: ZoneSummary) => {
      if (metric === "average") {
        const value = averageGridValue(zone)
        return value === null ? null : 100 * value / dollarMax
      }
      const score = metric === "grid_value"
        ? zone.grid_value_score
        : zone.drivers.find((item) => item.key === metric)?.score
      return score !== undefined && Number.isFinite(score) ? score : null
    },
    [metric, dollarMax]
  )

  // MapLibre "match" expression: zone code -> fill color.
  const fillColor = React.useMemo(
    () =>
      [
        "match",
        ["get", "code"],
        ...zones.flatMap((zone) => {
          const score = scoreOf(zone)
          return [zone.code, score === null ? NO_HISTORY_COLOR : scoreColor(score)]
        }),
        NO_HISTORY_COLOR,
      ] as unknown as string,
    [zones, scoreOf]
  )

  function onMove(e: MapLayerMouseEvent) {
    const code = e.features?.[0]?.properties?.code as string | undefined
    const container = e.target.getContainer()
    setHover(code ? {
      code,
      x: Math.max(8, Math.min(e.point.x + 12, container.clientWidth - 248)),
      y: Math.max(8, Math.min(e.point.y + 12, container.clientHeight - 200)),
    } : null)
  }

  const hovered = hover ? byCode[hover.code] : undefined
  const hoveredValue = hovered?.battery_values?.["40"]
  const hoveredDriver = hovered?.drivers.find((item) => item.key === metric)

  return (
    <div className={cn("min-w-0", className)} role="region" aria-label={`Load Zone map: ${metricLabel}`}>
      <div className="relative h-full overflow-hidden rounded-xl border">
        <Map
          initialViewState={{ bounds: TEXAS_BOUNDS, fitBoundsOptions: { padding: 24 } }}
          mapStyle={BASEMAP}
          interactiveLayerIds={["zones-fill"]}
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
          onClick={(e) => {
            const code = e.features?.[0]?.properties?.code
            if (code && byCode[code]) router.push(`/grid/${code}`)
          }}
          cursor={hover ? "pointer" : "grab"}
          scrollZoom={false} // let the wheel scroll the page; zoom with the buttons
          attributionControl={{ compact: true }}
        >
          <Source id="zones" type="geojson" data={ZONES_URL}>
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

        <Legend
          label={metricLabel}
          dollarMax={metric === "average" ? dollarMax : undefined}
          showNoHistory={zones.some((zone) => zone.on_map && averageGridValue(zone) === null)}
        />

        {hovered && hover && (
          <div
            className="pointer-events-none absolute z-10 w-60 rounded-lg border bg-background p-3 text-xs shadow-md"
            style={{ left: hover.x, top: hover.y }}
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-sm font-medium">{hovered.name}</span>
              <span className="font-mono text-muted-foreground">{hovered.code}</span>
            </div>
            {metric === "average" ? (
              hoveredValue ? (
                <div className="mt-2 flex flex-col gap-1">
                  <div className="font-medium">{formatLeadMoney(hoveredValue.value)}/yr · 40 kWh</div>
                  <div className="text-muted-foreground">{valueBasis(hoveredValue)}</div>
                  {averageGridValue(hovered) === null ? (
                    <div className="text-muted-foreground">Full-year history unavailable.</div>
                  ) : (
                    <div className="text-muted-foreground">Last 12 months: {formatLeadMoney(hoveredValue.recent)}/yr.</div>
                  )}
                </div>
              ) : (
                <div className="mt-2 text-muted-foreground">Historical grid value unavailable.</div>
              )
            ) : (
              <div className="mt-2 flex flex-col gap-1">
                {hoveredDriver ? (
                  <>
                    <div>{hoveredDriver.label}: <span className="font-medium">{formatDriverValue(hoveredDriver)}</span></div>
                    {hoveredDriver.key === "arbitrage" && <div className="text-muted-foreground">Reference battery (39.2 kWh, 11.5 kW)</div>}
                    <div className="text-muted-foreground">Relative driver score: {hoveredDriver.score.toFixed(0)}/100</div>
                  </>
                ) : (
                  <div>Zone Economics Score: <span className="font-medium">{hovered.grid_value_score.toFixed(0)}/100</span></div>
                )}
                <div className="text-muted-foreground">Relative to {zones.length} Load Zones · Last 12 months</div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function Legend({ label, dollarMax, showNoHistory }: { label: string; dollarMax?: number; showNoHistory: boolean }) {
  return (
    <div className="absolute bottom-3 left-3 flex max-w-[calc(100%_-_1.5rem)] flex-col gap-1 rounded-md border bg-background/90 px-3 py-2 text-xs">
      <div>{label}</div>
      <div
        className="h-2 w-40 rounded-full"
        style={{
          background: `linear-gradient(to right, ${[0, 25, 50, 75, 100].map(scoreColor).join(", ")})`,
        }}
      />
      <div className="flex w-40 justify-between text-muted-foreground">
        <span>{dollarMax ? "$0" : "0"}</span>
        <span>{dollarMax ? formatLeadMoney(dollarMax / 2) : "50"}</span>
        <span>{dollarMax ? formatLeadMoney(dollarMax) : "100"}</span>
      </div>
      {dollarMax ? showNoHistory && (
        <div className="mt-1 flex items-center gap-1.5 text-muted-foreground">
          <span className="size-2.5 rounded-sm" style={{ background: NO_HISTORY_COLOR }} aria-hidden="true" />
          Full-year history unavailable
        </div>
      ) : (
        <div className="text-muted-foreground">Relative score · Last 12 months</div>
      )}
    </div>
  )
}
