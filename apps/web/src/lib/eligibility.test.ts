// Run with `pnpm test` (node --test; Node strips the types, no test framework needed).
import assert from "node:assert/strict"
import { test } from "node:test"

import { CHECK_IDS, evaluate, SAMPLE_PLAN, type PlanReading } from "./eligibility.ts"

// A reading where the model answered "yes" to every check, with passing measurements.
function reading(overrides: Partial<PlanReading> = {}, checks: PlanReading["checks"] = {}): PlanReading {
  const yes = Object.fromEntries(CHECK_IDS.map((id) => [id, { status: "yes" as const, note: `${id} ok` }]))
  return {
    main_breaker_amps: 200,
    solar: "no",
    wall_run_ft: 11,
    side_clearance_in: 114,
    ...overrides,
    checks: { ...yes, ...checks },
  }
}

const statusOf = (r: ReturnType<typeof evaluate>, id: string) => r.requirements.find((q) => q.id === id)?.status

test("the sample plan set is eligible with a full score", () => {
  const r = evaluate(SAMPLE_PLAN.reading)
  assert.equal(r.verdict, "yes")
  assert.equal(r.score, 100)
  assert.deepEqual(
    r.requirements.map((q) => [q.id, q.status]),
    [["C1", "yes"], ["C2", "yes"], ["C3", "yes"], ["C4", "yes"], ["C5", "yes"], ["C6", "yes"]],
  )
})

test("measurements override the model's own answer", () => {
  const r = evaluate(reading({ wall_run_ft: 5 }))
  assert.equal(statusOf(r, "C3"), "no")
  assert.equal(r.verdict, "no")
  assert.match(r.requirements.find((q) => q.id === "C3")!.notes.join(" "), /5 ft of clear wall/)
})

test("a main breaker outside 100-200A fails the panel requirement", () => {
  assert.equal(statusOf(evaluate(reading({ main_breaker_amps: 400 })), "C1"), "no")
  assert.equal(statusOf(evaluate(reading({ main_breaker_amps: 90 })), "C1"), "no")
  assert.equal(statusOf(evaluate(reading({ main_breaker_amps: 150 })), "C1"), "yes")
})

test("solar needs a 200A panel", () => {
  assert.equal(statusOf(evaluate(reading({ solar: "yes", main_breaker_amps: 150 })), "C1"), "no")
  assert.equal(statusOf(evaluate(reading({ solar: "yes", main_breaker_amps: 200 })), "C1"), "yes")
})

test("side clearance under 56 in fails", () => {
  assert.equal(statusOf(evaluate(reading({ side_clearance_in: 40 })), "C4"), "no")
})

test("a measured zero is a measurement, not a missing value", () => {
  assert.equal(statusOf(evaluate(reading({ side_clearance_in: 0 })), "C4"), "no")
  assert.equal(statusOf(evaluate(reading({ wall_run_ft: 0 })), "C3"), "no")
})

test("no solar passes even when the breaker size is unknown", () => {
  const r = evaluate(reading({ main_breaker_amps: null, solar: "no" }, { E3: { status: "inconclusive", note: "" } }))
  assert.equal(statusOf(r, "C1"), "yes")
})

test("uneven ground at the pad fails the wall-space requirement", () => {
  const r = evaluate(reading({}, { S8: { status: "no", note: "steep grade" } }))
  assert.equal(statusOf(r, "C3"), "no")
})

test("an inconclusive or missing check needs review and costs half a requirement", () => {
  const r = evaluate(reading({}, { E6: { status: "inconclusive", note: "panel location not shown" } }))
  assert.equal(statusOf(r, "C6"), "maybe")
  assert.equal(r.verdict, "maybe")
  assert.equal(r.score, 92) // (5 × 100 + 50) / 6

  const withoutGas = reading()
  delete withoutGas.checks.S5
  assert.equal(statusOf(evaluate(withoutGas), "C5"), "maybe")
})

test("any failed requirement makes the house not eligible, whatever the rest", () => {
  const r = evaluate(reading({ side_clearance_in: 40 }, { E6: { status: "inconclusive", note: "" } }))
  assert.equal(r.verdict, "no")
  assert.equal(r.score, 75) // (4 × 100 + 50 + 0) / 6 = 75
})
