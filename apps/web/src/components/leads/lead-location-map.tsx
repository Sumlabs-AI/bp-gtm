"use client"

import { setWorkerUrl } from "maplibre-gl"
import Map, { Marker, NavigationControl } from "react-map-gl/maplibre"
import "maplibre-gl/dist/maplibre-gl.css"

import { scoreColor } from "@/lib/grid"

const BASEMAP = "https://tiles.openfreemap.org/styles/positron"

// See src/app/maplibre/[file]/route.ts.
if (typeof window !== "undefined") setWorkerUrl("/maplibre/maplibre-gl-worker.mjs")

export function LeadLocationMap({ lat, lon, score }: { lat: number; lon: number; score: number }) {
  return (
    <div className="h-[260px] overflow-hidden rounded-lg border">
      <Map
        initialViewState={{ longitude: lon, latitude: lat, zoom: 15 }}
        mapStyle={BASEMAP}
        scrollZoom={false}
        attributionControl={{ compact: true }}
      >
        <Marker longitude={lon} latitude={lat} anchor="center">
          <div
            className="size-4 rounded-full border-2 border-white shadow-md"
            style={{ backgroundColor: scoreColor(score) }}
            aria-label="Lead location"
            role="img"
          />
        </Marker>
        <NavigationControl position="top-right" showCompass={false} />
      </Map>
    </div>
  )
}
