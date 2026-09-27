# Install eligibility (proof of concept)

The **Eligibility** card, the last card in the lead drawer's Home section, answers "can this home host a Base battery?" from an architectural plan set. It is a proof of concept: every home uses the same sample plan set, the plan reading is recorded rather than computed, and the result feeds nothing else. It does not change the lead score, sort, filters or export, and nothing is stored.

It comes from a hackathon prototype that had a model read uploaded drawings. Only its install rules were kept.

## How it works

All of it lives in the web app, with no API endpoint and no model call:

- `apps/web/src/lib/eligibility.ts` (pure):
  - **`PlanReading`** is what a reader extracts from a plan set: main breaker amps, solar, clear wall run from the meter (ft), side clearance (in), and a yes / no / inconclusive answer per drawing check (E1…E10, S1…S10).
  - **`evaluate(reading)`** turns a reading into a result:
    1. Applies the measured rules, which override the reader's own answer: breaker 100–200A; solar needs 200A; wall run ≥ 6 ft; side clearance ≥ 56 in.
    2. Rolls the checks up into six requirements: Panel size, Meter location, Wall space, Side clearance, Gas meter, Working space. A requirement is ✗ if any of its checks fails, ✓ if all pass, otherwise it needs review.
    3. Returns a verdict: Eligible, Needs review, or Not eligible. Any ✗ means Not eligible.
    4. Returns a score from 0 to 100: the average over the six requirements, with ✓ = 100, needs review = 50, ✗ = 0.
  - **`SAMPLE_PLAN`** is the one plan set plus the reading a model returned for it. The plan set is 4 sheets, "illustrative sample, not for construction".
- `apps/web/src/components/gtm/eligibility-section.tsx`: the "Calculate eligibility" button.
  - Clicking it steps through about 1.5 s of progress text, then shows the verdict, score, a site-plan thumbnail (`public/eligibility/site-plan.svg`, which opens full size) and the six requirements with the drawing notes behind each one.
  - Results stay in memory per lead until the page reloads.

## Changes from the prototype

- The E3 check (solar needs 200A) now counts toward Panel size, and S8 (level ground, flood zone) toward Wall space. In the prototype they fed no requirement, so they could never fail a home.
- Dropped:
  - the Austin 150A rule and the address checks, because there is one plan set for every home;
  - the single vs double battery sizing, which would contradict the lead's own 25/40/50 kWh sizing;
  - the address-only public-data screen.

## Making it real

To make it real, replace `SAMPLE_PLAN.reading` with a real reading of the home's own plans. That means a model call behind an API endpoint, with the key kept server-side. `evaluate` stays the same.

Tests: `apps/web/src/lib/eligibility.test.ts` (`pnpm test` in `apps/web`).
