"use client"

import * as React from "react"
import { CheckIcon, CircleHelpIcon, Loader2Icon, XIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { evaluate, SAMPLE_PLAN, type Eligibility, type Status } from "@/lib/eligibility"

// Results survive closing the drawer, for the session only: nothing is stored.
const results = new Map<number, Eligibility>()

// The reading is recorded, so it's instant; the steps give it the pace of a real read.
const STEPS = ["Finding the plan set…", "Reading 4 sheets…", "Checking 6 requirements…"]
const STEP_MS = 500

const VERDICT: Record<Status, { label: string; className: string }> = {
  yes: { label: "Eligible", className: "bg-emerald-600 text-white" },
  maybe: { label: "Needs review", className: "border border-amber-500 text-amber-700" },
  no: { label: "Not eligible", className: "bg-red-600 text-white" },
}

/** Proof of concept: can this home host a Base battery, per its plan set (wiki/eligibility.md). */
export function EligibilitySection({ leadId }: { leadId: number }) {
  const [, rerender] = React.useReducer((n: number) => n + 1, 0)
  const [step, setStep] = React.useState<{ leadId: number; index: number } | null>(null)
  const result = results.get(leadId)
  const running = step?.leadId === leadId

  React.useEffect(() => {
    if (!running) return
    const timer = setTimeout(() => {
      if (step.index < STEPS.length - 1) return setStep({ leadId, index: step.index + 1 })
      results.set(leadId, evaluate(SAMPLE_PLAN.reading))
      setStep(null)
      rerender()
    }, STEP_MS)
    return () => clearTimeout(timer)
  }, [running, step, leadId])

  return (
    <div className="mx-4 rounded-lg border p-3 text-sm">
      {result ? (
        <EligibilityResult result={result} />
      ) : (
        <div className="flex items-center gap-3">
          <p className="min-w-0 flex-1 text-xs text-muted-foreground">
            {running ? STEPS[step.index] : "Check this home's plan set against Base's install requirements."}
          </p>
          <Button size="sm" disabled={running} onClick={() => setStep({ leadId, index: 0 })}>
            {running && <Loader2Icon className="animate-spin" aria-hidden />}
            Calculate eligibility
          </Button>
        </div>
      )}
    </div>
  )
}

function EligibilityResult({ result }: { result: Eligibility }) {
  const verdict = VERDICT[result.verdict]
  const { main_breaker_amps: amps, wall_run_ft: run, side_clearance_in: clr } = SAMPLE_PLAN.reading
  return (
    <div className="flex flex-col gap-3">
      <div className="flex gap-3">
        <a
          href={SAMPLE_PLAN.image}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 overflow-hidden rounded-md border hover:border-primary"
          title="Open the site plan"
        >
          {/* A static SVG from public/; next/image adds nothing for it. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={SAMPLE_PLAN.image} alt="Site plan sheet from the sample plan set" className="h-20 w-30 bg-white object-cover" />
        </a>
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${verdict.className}`}>{verdict.label}</span>
            <span className="text-lg font-semibold tabular-nums">{result.score}</span>
            <span className="text-xs text-muted-foreground">/ 100</span>
          </div>
          <p className="text-xs font-medium">{SAMPLE_PLAN.title}</p>
          <p className="text-xs text-muted-foreground">
            {SAMPLE_PLAN.sheets}. Found a {amps}A main breaker, {run} ft of clear wall at the meter and {clr} in of side clearance.
          </p>
        </div>
      </div>
      <ul className="flex flex-col divide-y rounded-md border">
        {result.requirements.map((r) => (
          <li key={r.id}>
            <details className="group">
              <summary className="flex cursor-pointer list-none items-start gap-2 px-2.5 py-2 hover:bg-muted/50 [&::-webkit-details-marker]:hidden">
                <StatusIcon status={r.status} />
                <span className="min-w-0">
                  <span className="block text-xs font-medium">{r.label}</span>
                  <span className="block text-[11px] text-muted-foreground">{r.metric}</span>
                </span>
              </summary>
              <ul className="list-disc space-y-0.5 pr-3 pb-2 pl-10 text-[11px] text-muted-foreground">
                {r.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </details>
          </li>
        ))}
      </ul>
    </div>
  )
}

function StatusIcon({ status }: { status: Status }) {
  if (status === "yes") return <CheckIcon className="mt-0.5 size-4 shrink-0 text-emerald-600" aria-label="Meets" />
  if (status === "no") return <XIcon className="mt-0.5 size-4 shrink-0 text-red-600" aria-label="Fails" />
  return <CircleHelpIcon className="mt-0.5 size-4 shrink-0 text-amber-600" aria-label="Needs review" />
}
