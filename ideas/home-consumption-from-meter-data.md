# Idea: calibrate home electricity estimates with real meter data (v2, v3)

Status: **later** (captured 2026-09-27). Not scheduled. v1, a property-based estimate from
public data (ResStock + ERCOT load profiles + Census heating fuel), is being built first.
See `wiki/residential-leads.md` once it lands.

## Why

v1 can only explain about 20–40% of the home-to-home variation in annual kWh. Published
studies and our own fits on EIA RECS agree: per-home error around 30–40% (MAPE), ±30–50%
on peak kW, while area totals land within 5–10%. That's enough to rank leads, not to size a
battery or quote a customer. The single most valuable missing fact is whether a home heats
with electricity (Texas RECS fit: R² 0.28 → 0.40 once heating fuel is known). Real meter
data fixes both the level and the fuel question.

## v2: learn from Base's own customers

As Retail Electric Provider of record, Base already receives, for its own customers only:

- Smart Meter Texas (SMT) 15-min interval data, daily and monthly reads, with a history
  backfill (`REPENROLL`, up to 24 months; confirm it includes usage before Base became the REP).
- ERCOT's private *ESI ID Service History & Usage Extract*, which includes the ERCOT **load
  profile code**. `RESHIWR` means winter-peaking (mostly electric heat), `RESLOWR` the rest.
  That's a true electric-heat label per customer.
- 867_02 historical usage (12 months, monthly) at enrollment, and 867_03 each billing cycle.

Sketch:

1. Build a labeled set of **3,000–5,000 homes** with 12 complete months of pre-battery SMT
   data, stratified by size, vintage, geography, pool and solar. After a battery is installed
   the meter shows grid flow net of the battery: use pre-install history, or rebuild gross load
   from our battery telemetry (meter + discharge − charge). Keep solar homes separate (the meter
   sees imports/exports, not the solar the home consumes itself).
2. Train gradient-boosted models on the same HCAD features as v1, plus the v1 estimate as a
   feature, for: annual kWh, monthly shape, 15-min peak kW, and P(electric heat) (labels from
   the profile code).
3. Validate on held-out ESI IDs, then held-out geography and time. Report median and
   90th-percentile absolute % error, monthly error, peak error and bias by pool/solar/size/
   vintage/fuel. Check that the P10–P90 range really covers ~80% of held-out homes.
4. Watch selection bias: Base customers aren't a random sample of Harris homes.

Guardrails (PUCT §25.472, PURA §39.107): customer data may be used for Base's own customers
and to train models, never shown or sold per customer to anyone else. Never present an
estimate as metered data.

## v3: real data for prospects, and a heating-fuel append

1. **Bill upload + OCR in the sales funnel.** A Texas bill shows the ESI ID, meter number and
   current REP. This gives at least one month of kWh right away.
2. **SMT consent step.** With the ESI ID, meter number, REP certificate number and the
   prospect's email, call SMT `NewAgreement`. The prospect clicks one approval email and we
   pull 12–24 months of 15-min data: a real annual total, shape and peak kW for sizing.
   - Start through an aggregator: Arcadia (Plug; sales-quoted) or Bayou Energy (~$2/meter).
     UtilityAPI dropped SMT in Sep 2025. meterplan.com already runs this exact flow for solar
     installers.
   - Build our own SMT Competitive Service Provider integration once volume justifies it:
     company SMT account with the CSP role, DUNS, static IP allowlist, mutual TLS, JWT since
     Sep 2025.
   - Fallback: an e-signed Letter of Authorization (§25.472(b)(3)). CenterPoint must return 12
     months of *monthly* kWh within 3 business days (Excel; or TX SET 814_26 via ERCOT).
   - Keep data-access consent separate from marketing (TCPA / Texas SB 140) consent.
3. **Heating-fuel append for top leads.** A CoreLogic property append includes a heating-fuel
   code (seen at ~$0.25/record via a reseller). Buy it for the top ~50k leads (~$12.5k) rather
   than all 772k, after testing Harris coverage on a sample.

## Later (not v2/v3)

- Aerial imagery (see [solar-detection-from-imagery.md](solar-detection-from-imagery.md)):
  NAIP (free, 60 cm) is enough for pools and solar, not AC condensers; 6-inch H-GAC imagery
  (~$20k for Harris) might count condensers but that's unproven. Google/Bing terms forbid
  deriving data from their imagery.
- Houston city HVAC / electrical-service permits (tonnage, panel upgrades, generators) aren't
  published in bulk; vendors (e.g. Shovels) sell classified permits.
- EV registrations by ZIP (H-GAC, DFW Clean Cities / Atlas EV Hub) as an area-level EV prior.

## Open questions

- SMT fees for CSPs/REPs, CSP history depth (12 vs 24 months), whether a REP can also hold
  the CSP role under the same DUNS (ask support@smartmetertexas.com).
- Status of CenterPoint's Usage History Inquiry Tool API (pages now 404).
- How Bayou connects to SMT (CSP flow vs customer credentials).
- CoreLogic heating-fuel coverage in Harris County.

## Sources

Research of 2026-09-26/27: SMT Interface Guide (2024), PUCT §25.130 / §25.472, ERCOT Retail
Market Guide (Feb 2026) §7.5, ERCOT ESI ID Service History & Usage Extract spec, Peplinski et
al. (Applied Energy, 58k SoCal homes: household annual R² 0.34 vs tract 0.82), Houston Home
Energy Efficiency Study (2009: cooling MAE 22% per home), EIA RECS 2020 microdata.
