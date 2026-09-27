import { Row, Score } from "@/components/need/score-parts"
import type { Opportunity, Timing } from "@/lib/need"

const fmt = (v: number | null) => (v === null ? "—" : v.toFixed(0))

const PHASE: Record<Timing["phase"], string> = {
  none: "no recent storm",
  pre_event: "alert in effect or due",
  peak: "post-storm buying window",
  fading: "post-storm window fading",
}

function timingLabel(t: Timing) {
  const since = t.daysSince === null ? "" : `, ended ${t.daysSince.toFixed(0)} d ago`
  return t.event ? `${PHASE[t.phase]} (${t.event}${since})` : PHASE[t.phase]
}

export function OpportunityBlock({ opportunity, timing }: { opportunity: Opportunity; timing?: Timing }) {
  return (
    <section className="flex flex-col gap-2 px-4 text-sm">
      <div className="flex items-center justify-between">
        <h3 className="font-medium">Opportunity</h3>
        <Score value={opportunity.score} />
      </div>
      <p className="text-xs text-muted-foreground">
        Where Base should target: the right homes (Propensity), a real reason for backup (Baseline Need) and the right
        moment (Timing: the weeks after a storm). A rank, not a probability.
      </p>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <Row label="Propensity (input)" value={fmt(opportunity.propensity)} />
        <Row label="Baseline Need (input)" value={fmt(opportunity.baselineNeed)} />
        <Row label="Before Timing" value={fmt(opportunity.baseScore)} />
        <Row label="Timing" value={`×${opportunity.timing.toFixed(2)}`} />
      </dl>
      {timing && timing.phase !== "none" && (
        <p className="text-xs font-medium">Timing: {timingLabel(timing)}</p>
      )}
      {opportunity.score === null && (
        <p className="text-xs text-muted-foreground">
          Needs both inputs: {opportunity.propensity === null ? "no Propensity (no eligible homes scored here)" : "no Baseline Need yet"}.
        </p>
      )}
      <p className="text-[11px] text-muted-foreground">{opportunity.method}</p>
      {opportunity.limitations.map((l) => (
        <p key={l} className="text-[11px] text-muted-foreground">{l}</p>
      ))}
    </section>
  )
}
