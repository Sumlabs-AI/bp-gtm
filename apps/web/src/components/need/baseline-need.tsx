import { Row, Score } from "@/components/need/score-parts"
import type { BaselineNeed } from "@/lib/need"

const DRIVER = {
  outage: "mostly outage history",
  weather: "mostly weather exposure",
  both: "outage history and weather together",
} as const

const fmt = (v: number | null) => (v === null ? "—" : v.toFixed(0))

export function BaselineNeedBlock({ baseline }: { baseline: BaselineNeed }) {
  return (
    <section className="flex flex-col gap-2 px-4 text-sm">
      <div className="flex items-center justify-between">
        <h3 className="font-medium">Baseline Need</h3>
        <Score value={baseline.baselineNeed} />
      </div>
      <p className="text-xs text-muted-foreground">
        Structural reason to benefit from backup power, as a Texas percentile
        {baseline.dominantDriver && <>: driven by {DRIVER[baseline.dominantDriver]}</>}. Not a purchase likelihood.
      </p>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <Row label="Observed Outage Exposure (input)" value={fmt(baseline.inputs.observedOutageExposure)} />
        <Row label="Weather Need (input)" value={fmt(baseline.inputs.weatherNeed)} />
        <Row label="Combined (before ranking)" value={fmt(baseline.raw)} />
        <Row label="Utility reliability (context)" value={fmt(baseline.context.utilityReliabilityNeed)} />
      </dl>
      <p className="text-[11px] text-muted-foreground">{baseline.method}</p>
      {[...baseline.notes, ...baseline.limitations].map((l) => (
        <p key={l} className="text-[11px] text-muted-foreground">{l}</p>
      ))}
    </section>
  )
}
