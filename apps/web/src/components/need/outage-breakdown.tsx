import { historyThrough, Row, Score } from "@/components/need/score-parts"
import type { OutageComponent } from "@/lib/need"

const number = (value: number | null, digits = 0) =>
  value === null ? "—" : value.toLocaleString("en-US", { maximumFractionDigits: digits })
const percent = (value: number | null) => (value === null ? "—" : `${(value * 100).toFixed(1)}%`)
export function OutageBreakdown({ outage }: { outage: OutageComponent }) {
  const utility = outage.utilityReliabilityNeed
  const observed = outage.observedOutageExposure
  return (
    <section className="flex flex-col gap-4 px-4 text-sm">
      <div className="flex items-center justify-between">
        <h3 className="font-medium">Outage Need</h3>
        <Score value={outage.score} />
      </div>

      {observed && (
      <div className="flex flex-col gap-2 rounded-lg border p-3">
        <div className="flex items-center justify-between">
          <span className="font-medium">Observed Outage Exposure</span>
          <Score value={observed.score} />
        </div>
        <p className="text-xs text-muted-foreground">
          {observed.county.name ?? observed.county.fips} County, Texas percentile. County-level: every Cell in the county
          shares it.
        </p>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          <Row label="Outage hours / customer (5 y)" value={number(observed.metrics.hoursPerCustomer5y, 1)} />
          <Row label="Major outage events (5 y)" value={number(observed.metrics.majorOutageEvents5y)} />
          <Row label="Outage events (5 y)" value={number(observed.metrics.outageEvents5y)} />
          <Row label="Peak share out (5 y)" value={percent(observed.metrics.peakPctOut5y)} />
          <Row label="Outage hours / customer (365 d)" value={number(observed.metrics.hoursPerCustomer365d, 1)} />
        </dl>
        <p className="text-xs">
          {observed.daysSinceLastObservedMajorOutage !== null
            ? `Last observed major outage: ${observed.daysSinceLastObservedMajorOutage} days ago`
            : observed.yearsObserved > 0
              ? "No major outage observed in the last 5 years"
              : "No outage history for this county"}
          <span className="text-muted-foreground"> · history through {historyThrough(observed.dataThrough)}</span>
        </p>
        <p className="text-[11px] text-muted-foreground">{observed.source}</p>
      </div>
      )}

      <div className="flex flex-col gap-2 rounded-lg border p-3">
        <div className="flex items-center justify-between">
          <span className="font-medium">Utility Reliability Need</span>
          <Score value={utility?.score ?? null} />
        </div>
        {utility ? (
          <>
            <p className="text-xs text-muted-foreground">
              {utility.utility.name}, Texas percentile of normal-conditions outage minutes.
            </p>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
              <Row label="SAIDI excl. major events (min/yr)" value={number(utility.metrics.saidiWithoutMed5y)} />
              <Row label="SAIDI incl. major events (min/yr)" value={number(utility.metrics.saidiWithMed5y)} />
              <Row label="SAIFI excl. major events" value={number(utility.metrics.saifiWithoutMed5y, 2)} />
            </dl>
            <p className="text-[11px] text-muted-foreground">
              {utility.source}, {utility.yearsUsed}-year mean through {utility.dataThroughYear}
            </p>
          </>
        ) : (
          <p className="text-xs text-muted-foreground">Utility unknown for this Cell.</p>
        )}
      </div>

      {outage.notes.map((note) => (
        <p key={note} className="text-xs text-muted-foreground">
          {note}
        </p>
      ))}
    </section>
  )
}
