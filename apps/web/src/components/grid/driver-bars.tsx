import { Progress } from "@/components/ui/progress"
import { formatDriverValue, type Driver } from "@/lib/grid"

// Compact list: one thin bar per driver, score 0-100 with the raw value beside it.
export function DriverBars({ drivers }: { drivers: Driver[] }) {
  return (
    <div className="grid gap-1.5">
      {drivers.map((d) => (
        <div key={d.key} className="grid grid-cols-[8.5rem_1fr_5.5rem] items-center gap-2 text-xs">
          <span className="truncate text-muted-foreground">{d.label}</span>
          <Progress value={d.score} aria-label={`${d.label} score`} />
          <span className="text-right tabular-nums">{formatDriverValue(d)}</span>
        </div>
      ))}
    </div>
  )
}
