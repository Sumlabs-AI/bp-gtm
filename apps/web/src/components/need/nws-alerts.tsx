import { Badge } from "@/components/ui/badge"
import type { AlertFeed } from "@/lib/need"

const time = (iso: string) =>
  new Date(iso).toLocaleString("en-US", { weekday: "short", hour: "numeric", minute: "2-digit", timeZoneName: "short" })

export function NwsAlerts({ feed }: { feed: AlertFeed }) {
  return (
    <section className="flex flex-col gap-3 px-4 text-sm">
      <div className="flex items-center justify-between">
        <h3 className="font-medium">Official NWS alerts</h3>
        {feed.stale && <Badge variant="destructive">Stale</Badge>}
      </div>
      {feed.signals.length === 0 ? (
        <p className="text-xs text-muted-foreground">No official NWS alert active for this Cell.</p>
      ) : (
        feed.signals.map((s) => (
          <div key={s.id} className="flex flex-col gap-1 rounded-lg border p-3 text-xs">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{s.event}</span>
              <Badge variant="outline">{s.severity ?? "—"}</Badge>
            </div>
            {s.headline && <p className="text-muted-foreground">{s.headline}</p>}
            <p>
              In effect until <span className="font-medium">{time(s.endsAt)}</span>
              <span className="text-muted-foreground">
                {" · "}
                {[s.certainty, s.urgency, s.geometrySource === "alert" ? "area from the alert" : "area from NWS zones"]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            </p>
          </div>
        ))
      )}
      <p className="text-[11px] text-muted-foreground">
        {feed.fetchedAt ? `Last NWS update received ${time(feed.fetchedAt)}` : "No NWS update received yet"}
        {feed.stale && " · may be out of date"}
      </p>
    </section>
  )
}
