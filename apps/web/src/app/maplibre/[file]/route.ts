import { readFile } from "node:fs/promises"
import path from "node:path"

// MapLibre loads its web worker from a URL next to its own bundle, which Turbopack
// doesn't emit. Serve the worker (and the shared module it imports) from node_modules;
// zone-map.tsx points maplibre's setWorkerUrl here.
const FILES = new Set(["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"])

export async function GET(_req: Request, ctx: RouteContext<"/maplibre/[file]">) {
  const { file } = await ctx.params
  if (!FILES.has(file)) return new Response("Not found", { status: 404 })
  const body = await readFile(path.join(process.cwd(), "node_modules/maplibre-gl/dist", file))
  return new Response(body, {
    headers: {
      "Content-Type": "text/javascript; charset=utf-8",
      "Cache-Control": "public, max-age=86400",
    },
  })
}
