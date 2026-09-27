"use client"

import { setWorkerUrl } from "maplibre-gl"
import Map, { Marker, NavigationControl } from "react-map-gl/maplibre"
import "maplibre-gl/dist/maplibre-gl.css"

import { cn } from "@/lib/utils"

const BASEMAP = "https://tiles.openfreemap.org/styles/positron"

// See src/app/maplibre/[file]/route.ts.
if (typeof window !== "undefined") setWorkerUrl("/maplibre/maplibre-gl-worker.mjs")

export function LeadLocationMap({ lat, lon, className }: { lat: number; lon: number; className?: string }) {
  return (
    <div className={cn("h-[260px] overflow-hidden rounded-lg border", className)}>
      <Map
        initialViewState={{ longitude: lon, latitude: lat, zoom: 15 }}
        mapStyle={BASEMAP}
        scrollZoom={false}
        attributionControl={{ compact: true }}
      >
        <Marker longitude={lon} latitude={lat} anchor="center">
          <div
            className="size-4 rounded-full border-2 border-white bg-primary shadow-md"
            aria-label="Lead location"
            role="img"
          />
        </Marker>
        <NavigationControl position="top-right" showCompass={false} />
      </Map>
    </div>
  )
}
