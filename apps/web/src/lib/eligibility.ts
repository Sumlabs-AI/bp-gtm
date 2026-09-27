// Install eligibility from a plan set: proof of concept (wiki/eligibility.md).
// A reader (in production, a model reading the architectural drawings) answers the install
// checks below; `evaluate` applies Base's install rules to that answer and rolls it up into
// six requirements, a verdict and a score. Every house uses the same sample plan set for now,
// and its reading is recorded, not computed: there is no model call.

export type Status = "yes" | "no" | "maybe"

type Check = { status: "yes" | "no" | "inconclusive"; note: string }

/** What a reader extracts from a plan set. */
export type PlanReading = {
  main_breaker_amps: number | null
  solar: "yes" | "no" | "unknown"
  wall_run_ft: number | null
  side_clearance_in: number | null
  checks: Partial<Record<string, Check>>
}

export type Requirement = { id: string; label: string; metric: string; status: Status; notes: string[] }

export type Eligibility = { verdict: Status; score: number; requirements: Requirement[] }

// Base's install requirements, each backed by the drawing checks that decide it.
const REQUIREMENTS = [
  { id: "C1", label: "Panel size", metric: "100–200A main breaker, one main panel, 200A if solar", checks: ["E1", "E3", "E4"] },
  { id: "C2", label: "Meter location", metric: "Outside wall, 6 ft high or less, panel on the same wall", checks: ["E5", "E7", "S10"] },
  { id: "C3", label: "Wall space", metric: "6 ft of clear, level wall from the meter, no windows", checks: ["S1", "E10", "S6", "S3", "S4", "S2", "S8"] },
  { id: "C4", label: "Side clearance", metric: "56 in from the wall to a fence or lot line", checks: ["S7"] },
  { id: "C5", label: "Gas meter", metric: "3 ft from the battery, or no gas service", checks: ["S5"] },
  { id: "C6", label: "Working space", metric: "Clear space at meter and panel, panel not in a closet, meter secure", checks: ["E8", "E6", "E9"] },
] as const

export const CHECK_IDS: string[] = REQUIREMENTS.flatMap((r) => [...r.checks])

const POINTS: Record<Status, number> = { yes: 100, maybe: 50, no: 0 }

export function evaluate(reading: PlanReading): Eligibility {
  const checks = new Map<string, { status: Status; note: string }>()
  for (const id of CHECK_IDS) {
    const c = reading.checks[id]
    const status: Status = c?.status === "yes" ? "yes" : c?.status === "no" ? "no" : "maybe"
    checks.set(id, { status, note: c?.note ?? "" })
  }
  // The measured values decide their checks, whatever the reader answered for them.
  const rule = (id: string, status: Status, why: string) => {
    const old = checks.get(id)!
    const note = !old.note ? why : old.status === status ? old.note : `${old.note} · Rule: ${why}`
    checks.set(id, { status, note })
  }
  const amps = reading.main_breaker_amps
  if (amps != null) {
    rule("E1", amps >= 100 && amps <= 200 ? "yes" : "no", `${amps}A main breaker.`)
    if (reading.solar === "yes") rule("E3", amps === 200 ? "yes" : "no", `Solar with a ${amps}A main breaker.`)
  }
  if (reading.solar === "no") rule("E3", "yes", "No solar on the drawings.")
  const run = reading.wall_run_ft
  if (run != null) rule("S1", run >= 6 ? "yes" : "no", `${run} ft of clear wall from the meter.`)
  const clr = reading.side_clearance_in
  if (clr != null) rule("S7", clr >= 56 ? "yes" : "no", `${clr} in from the wall to the nearest obstruction.`)

  const requirements = REQUIREMENTS.map(({ id, label, metric, checks: ids }) => {
    const parts = ids.map((c) => checks.get(c)!)
    const status: Status = parts.some((p) => p.status === "no") ? "no" : parts.every((p) => p.status === "yes") ? "yes" : "maybe"
    const notes = [...new Set(parts.map((p) => p.note).filter(Boolean))]
    return { id, label, metric, status, notes }
  })
  const statuses = requirements.map((r) => r.status)
  const verdict: Status = statuses.includes("no") ? "no" : statuses.every((s) => s === "yes") ? "yes" : "maybe"
  const score = Math.round(statuses.reduce((sum, s) => sum + POINTS[s], 0) / statuses.length)
  return { verdict, score, requirements }
}

// The one plan set every house uses for now: a synthetic, illustrative drawing set
// (not for construction), with the reading a model returned for it.
export const SAMPLE_PLAN = {
  title: "Sample plan set · 4 sheets",
  sheets: "Site plan, electrical, elevation, compliance summary",
  image: "/eligibility/site-plan.svg",
  reading: {
    main_breaker_amps: 200,
    solar: "no",
    wall_run_ft: 11,
    side_clearance_in: 114,
    checks: {
      E1: { status: "yes", note: "E1.0 riser: new 200A main breaker; old 100A fuse panel removed." },
      E3: { status: "yes", note: "A1.0 note 7 and E1.0: no photovoltaic system." },
      E4: { status: "yes", note: "E1.0: one main panel, no subpanels." },
      E5: { status: "yes", note: "E1.0 partial plan: panel back-to-back with the exterior meter on the east wall." },
      E6: { status: "yes", note: "E1.0: panel on the utility room wall, not a closet." },
      E7: { status: "yes", note: "A3.0 and E1.0 schedule: meter 5'-0\" to center." },
      E8: { status: "yes", note: "E1.0: 36\" × 30\" working space at meter and panel." },
      E9: { status: "yes", note: "E1.0 note 4: new meter socket and mast, securely attached." },
      E10: { status: "yes", note: "E1.0 note 2: 30\" clear wall beside the meter for the transfer switch." },
      S1: { status: "yes", note: "A1.0 and A3.0: 11'-0\" clear east wall from the meter, no windows or doors." },
      S2: { status: "yes", note: "A1.0: two 3' × 3' pads drawn on the east wall." },
      S3: { status: "yes", note: "A1.0 note 4: pads within 20'-0\" of the meter, surface harness." },
      S4: { status: "yes", note: "A1.0 note 4: pads within 1'-0\" of the wall." },
      S5: { status: "yes", note: "A1.0 note 2: gas meter on the west wall, opposite side of the house." },
      S6: { status: "yes", note: "A3.0: windows at 11'-0\" and 18'-0\" from the meter, beyond the battery zone." },
      S7: { status: "yes", note: "A1.0: east side yard 9'-6\" (114\") wall to fence." },
      S8: { status: "yes", note: "A1.0 note 6: pad grade level ±1%; FEMA Zone X." },
      S10: { status: "yes", note: "A1.0 note 1: meter on the exterior east wall." },
    },
  } satisfies PlanReading,
}
