import { Badge } from "@/components/ui/badge"
import type { LiveGrid } from "@/lib/need"

const time = (iso: string) =>
  new Date(iso).toLocaleString("en-US", { weekday: "short", hour: "numeric", minute: "2-digit" })

export function LiveGridSection({ grid }: { grid: LiveGrid }) {
  const { condition, prices } = grid
  return (
    <section className="flex flex-col gap-3 px-4 text-sm">
      <h3 className="font-medium">ERCOT grid</h3>

      <div className={`flex flex-col gap-1 rounded-lg border p-3 text-xs ${condition.official ? "border-red-500" : ""}`}>
        <div className="flex items-center justify-between gap-2">
          <span className="font-medium">Official ERCOT condition</span>
          {condition.stale && <Badge variant="outline" className="border-amber-500 text-amber-700">Stale</Badge>}
        </div>
        <p>
          {condition.title ?? "No ERCOT update received yet"}
          {condition.prcMw !== null && (
            <span className="text-muted-foreground"> · reserves (PRC) {condition.prcMw.toLocaleString("en-US")} MW</span>
          )}
        </p>
        {condition.fetchedAt && <p className="text-[11px] text-muted-foreground">Fetched {time(condition.fetchedAt)}</p>}
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-xs font-medium">Grid stress (our reading of ERCOT data)</span>
        {grid.stressSignals.length === 0 ? (
          <p className="text-xs text-muted-foreground">None of our grid stress thresholds is crossed.</p>
        ) : (
          grid.stressSignals.map((s) => (
            <div key={s.type} className="flex flex-col gap-1 rounded-lg border border-dashed border-amber-500 p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span>{s.message}</span>
                <Badge variant="outline">{s.category}</Badge>
              </div>
              {s.at && <span className="text-muted-foreground">{time(s.at)}</span>}
            </div>
          ))
        )}
      </div>

      <p className="text-[11px] text-muted-foreground">
        {prices.loadZone ? `Load Zone ${prices.loadZone}` : "No Load Zone"}
        {prices.latestRt &&
          ` · latest real-time price $${prices.latestRt.price.toFixed(2)}/MWh at ${time(prices.latestRt.intervalStart)}`}
        {prices.stale && prices.loadZone && " · prices stale"}
      </p>
      {grid.notes.map((n) => (
        <p key={n} className="text-xs text-muted-foreground">{n}</p>
      ))}
    </section>
  )
}
