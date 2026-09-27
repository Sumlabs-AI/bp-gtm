import { historyThrough, Row, Score } from "@/components/need/score-parts"
import type { Propensity } from "@/lib/need"

export function PropensityBlock({ propensity }: { propensity: Propensity | null }) {
  return (
    <section className="flex flex-col gap-2 px-4 text-sm">
      <div className="flex items-center justify-between">
        <h3 className="font-medium">Propensity</h3>
        <Score value={propensity?.score ?? null} />
      </div>
      <p className="text-xs text-muted-foreground">
        Likelihood of battery adoption here, predicted by the ML propensity model from permit
        history and home values, ranked within the metro. Not Need: combined with Baseline Need
        only in the Opportunity Score.
      </p>
      {propensity ? (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          <Row label="Model" value={propensity.modelVersion} />
          <Row label="Scored" value={historyThrough(propensity.scoredAt)} />
          <Row label="Need feature version" value={propensity.featureVersion} />
        </dl>
      ) : (
        <p className="text-xs text-muted-foreground">No prediction imported for this Cell yet.</p>
      )}
    </section>
  )
}
