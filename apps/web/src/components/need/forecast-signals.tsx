import { Badge } from "@/components/ui/badge"
import type { ForecastFeed, ForecastSignal } from "@/lib/need"

const time = (iso: string) =>
  new Date(iso).toLocaleString("en-US", { weekday: "short", hour: "numeric", minute: "2-digit" })

const CONDITION: Record<ForecastSignal["condition"], string> = {
  wind: "Dangerous wind gusts",
  heat: "Extreme heat index",
  cold: "Extreme cold",
  ice: "Ice accumulation",
  severe_storm: "Severe storm risk",
}

function describe(s: ForecastSignal): string {
  if (s.source === "spc_outlook") return `SPC outlook: ${s.label}`
  const op = s.comparison === "<=" ? "≤" : "≥"
  const threshold = `our threshold ${op} ${s.threshold}${s.unit}`
  if (s.peakValue === null) return threshold
  return `peak ${Math.round(s.peakValue * 100) / 100}${s.unit} (${threshold})`
}

function when(s: ForecastSignal): string {
  if (new Date(s.startAt) <= new Date()) return `under way until ${time(s.endAt)}`
  return `${time(s.startAt)} – ${time(s.endAt)} · starts in ${Math.max(1, Math.round(s.leadHours))} h`
}

export function ForecastSignals({ feed }: { feed: ForecastFeed }) {
  return (
    <section className="flex flex-col gap-3 px-4 text-sm">
      <div className="flex items-center justify-between">
        <h3 className="font-medium">Forecast (our reading of NWS/SPC data)</h3>
        <div className="flex gap-1">
          {feed.grid.stale && <Badge variant="outline" className="border-amber-500 text-amber-700">NWS grid stale</Badge>}
          {feed.spc.stale && <Badge variant="outline" className="border-amber-500 text-amber-700">SPC stale</Badge>}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Not official alerts: periods in the next {feed.horizonHours} h where NWS forecast values cross our thresholds,
        or SPC severe-storm risk areas. Sampled once for the surrounding H3 res {feed.resolution} area{" "}
        <span className="font-mono">{feed.sourceCell}</span>, not for this Cell alone.
      </p>
      {feed.signals.length === 0 ? (
        <p className="text-xs text-muted-foreground">No forecast threshold crossed.</p>
      ) : (
        feed.signals.map((s) => (
          <div
            key={`${s.source}-${s.condition}-${s.startAt}`}
            className="flex flex-col gap-1 rounded-lg border border-dashed border-amber-500 p-3 text-xs"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{CONDITION[s.condition]}</span>
              <Badge variant="outline">{s.level}</Badge>
            </div>
            <p>{describe(s)}</p>
            <p className="text-muted-foreground">{when(s)}</p>
          </div>
        ))
      )}
      <p className="text-[11px] text-muted-foreground">
        {feed.grid.sourceUpdatedAt ? `NWS forecast issued ${time(feed.grid.sourceUpdatedAt)}` : "No NWS forecast yet"}
        {feed.grid.fetchedAt && ` · fetched ${time(feed.grid.fetchedAt)}`}
        {` · SPC ${feed.spc.fetchedAt ? `fetched ${time(feed.spc.fetchedAt)}` : "not fetched yet"}`}
      </p>
    </section>
  )
}
