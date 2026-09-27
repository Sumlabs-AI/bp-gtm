# Propensity research: process and discoveries

How the Propensity work actually went during the hackathon (Sept 25-27, 2026): what the plan expected, how each data
workstream played out, what the modelling found, and the discoveries along the way. Terms: [`CONTEXT.md`](../CONTEXT.md).

- **Result:** [propensity.md](propensity.md) (the rule in production) and [ADR 0002](../docs/adr/0002-propensity-home-value-rule.md).
- **Experiment details and numbers:** [`ml/RESEARCH.md`](../ml/RESEARCH.md). **Commands and full tables:** [`ml/README.md`](../ml/README.md).
- **Starting point:** the plan `ml/base_gtm_ml_plan.txt` and the data inventory `ml/base_gtm_data_table.txt`.

## 1. What the plan expected

A LightGBM Poisson model per Census block group: label = generator + battery installs from city permits per
1,000 eligible homes; features = Census ACS "fit" variables, parcel aggregates, installability, solar rate,
density; no outage data (that stays in Need). It had to beat an income-only ranking, a hand-built fit formula and
past installs, under spatial CV, leave-one-city-out and a temporal split (train ≤ 2023, predict 2024-2025).
Output: a percentile within the metro feeding `Priority = Eligibility × Installable × Propensity^0.6 × Need^0.4`.

The plan named its own biggest risks; two of them decided the outcome: **#2 "model just learns rich
neighborhoods"** and **#6 "data engineering eats the weekend"**.

## 2. Three data workstreams, run in parallel

Each ran as its own work session and wrote into `ml/`.

### 2.1 Permit labels (`ml/permits/`)

1. **Which cities.** Only cities publishing permits with a free-text description, a date and a location work.
   Austin (Socrata, 2016+, coordinates, status, contractor) and San Antonio (bulk CSVs, 2020+) passed. Dallas'
   feed stops in mid-2020. Fort Worth was added later (§4). Houston was not checked.
2. **Keyword label v0** as a fallback: 7,650 backup installs, with the jump from 2021 (Winter Storm Uri).
3. **Gold set:** 300 permits split into tune / test halves. Hand labeling was replaced by two LLMs labeling
   independently (gpt-6-luna, then gpt-6-astra): **98% agreement** (294 / 300); astra's labels are gold and the 6
   disagreements were adjudicated with written reasons.
4. **Jev** (a small classifier model answering yes/no and pick-one questions about each permit) was tuned on the
   tune half. One wording fix mattered: "permanently installed standby generator" was read too literally and
   missed San Antonio's "Generator Install <name>" permits. On the untouched test half: **Jev 92.9% accuracy /
   89.5% precision / 82.9% recall vs keywords 92.2% / 85.4% / 85.4%**. Jev's gain is precision (fewer gas lines,
   cell towers and repairs counted as installs).
5. **Rules kept in code, not in the model:** plumbing / gas permits never count (the generator's electrical
   permit already does); repeats at the same address within 180 days count once; expired / withdrawn permits
   are kept as a separate "intent" count; Base Power permits stay out of the label (validation only).
6. **Label v1:** 4,415 backup installs Mar 2021-Dec 2025 (3,637 Austin, 778 San Antonio), about $2 of Jev calls
   for ~42k permits, all answers cached.
7. **Checks:** generator vs battery rank correlation across block groups was 0.65 in Austin, so they were combined
   into one "backup" label (San Antonio 0.25, with only 81 batteries: its battery permits often carry just a
   name). Block-group counts are low (San Antonio median 0) but carry signal: the top 20% of block groups in
   2021-2023 held ~60% of 2024-2025 installs; moving to tracts barely helped, so block groups stayed.

### 2.2 Home parcels (`ml/parcels/`)

1. **Plan:** the TxGIO StratMap statewide parcel layer first, county exports for missing fields.
2. **Blocked:** StratMap's download server answered 403 to every scripted request. Travis and Bexar were pulled
   from their county GIS services instead; StratMap zips were later downloaded by hand in a browser.
3. **Install rules from Base's help center** (3 × 3 ft battery, 3 ft clearances, within 20 ft of the meter,
   100-200A main breaker, 150-200A in Austin, nothing above 200A) became proxies in one `INSTALL_RULES` dict
   (e.g. living area < 4,500 sq ft as a stand-in for ≤ 200A service, built ≥ 1980 in Austin). Building
   footprints were never added, so `installable_share` stayed weak outside Austin.
4. **Owner-occupancy:** Bexar has the homestead exemption code. Travis' homestead field was set on 96% of homes,
   so owner-occupied became "mailing address = property address" (77%), the proxy used for every county since.
5. **Checks:** eligible homes vs ACS correlation 0.80-0.93 per county; 90% (Austin) / 93% (San Antonio) of
   backup permits land on single-family parcels, and those homes are 90-93% owner-occupied vs 68-77% for all
   single-family homes.
6. **Scale-up (end of the weekend):** 22 counties across the Austin, San Antonio, DFW and Houston metros (§5).

### 2.3 Census ACS (`ml/acs/`)

1. api.census.gov now requires a key, so the pipeline reads the Census table-based summary files instead:
   24 tables, two vintages (2020-2024 main, 2017-2021 for temporal checks), both on 2020 block groups.
2. **Validated:** 2,280 / 2,280 values match Census Reporter; totals, universes and hand recomputes agree.
3. **Found and fixed:** category brackets move between vintages (the "moved in recently" lines mean 2020+ in one
   release and 2015+ in another), so the build now stops if any line's meaning changes; income is in each
   vintage's own dollars.
4. **Noise:** 16.8% of block groups flagged low-confidence; three features too unstable between vintages were
   dropped.
5. **First look at the label:** median home value alone had ρ = 0.70 with the install rate. The first warning
   that wealth would dominate. Details: [`ml/acs/ANALYSIS.md`](../ml/acs/ANALYSIS.md).

## 3. Modelling: from the plan's model to a rule

In order (numbers in [`ml/RESEARCH.md`](../ml/RESEARCH.md)):

1. **Training table:** 1,313 block groups ≥ 90% inside Austin or San Antonio (permits stop at city limits).
2. **Baselines first**, then LightGBM Poisson with a per-city offset: it tied median home value and did not
   transfer between cities. A Poisson GLM transferred but also only tied home value.
3. **Diagnosis:** model and home-value rankings shared two-thirds of their top areas; blending added < 0.012 AUC.
4. **Home level:** ranking each home by its own appraised value beat any area ranking by 10-15 points; LightGBM on
   all parcel attributes tied that single number again.
5. **Permit history:** solar owners bought backup ~3× more often at the same value, so the rule doubles their
   value. EV chargers, panel upgrades and pools stayed inconclusive.
6. **Decision:** Propensity = home-value rule, ML stopped ([ADR 0002](../docs/adr/0002-propensity-home-value-rule.md)).

## 4. Discoveries

- **Permit counts measure paperwork as much as demand.** Austin shows 7× San Antonio's install rate per eligible
  home. Every model and metric had to work *within* a city.
- **Wealth dominates backup buying.** In Austin, installs per 1,000 homes rise from 3.3 in the cheapest tenth of
  homes to 67 in the top tenth and 125 in the top 1%. Census features beyond home value add nothing measurable.
- **Resolution beats features.** The same variable (home value) at home level instead of area level is worth
  more than every extra feature tried. About two-thirds of that gain is resolution, one-third the better source
  (appraisal vs survey).
- **ACS undercounts eligible homes in mixed neighborhoods**, which briefly taught the model a fake
  "single-family → fewer installs" effect. Parcel counts fixed it.
- **Trees learn places, not buyers.** LightGBM dropped sharply when tested on the other city; it also learned ZIP
  identity when emPOWER (ZIP-level medical-equipment data) was added.
- **Solar-plus-storage is a different buyer from backup power.** Fort Worth only publishes descriptions on
  building permits, so its generators are invisible and 97% of its batteries come with solar. Nothing ranks those
  buyers, not even home value. Newer, mortgaged, middle-income homes buy them.
- **Existing solar owners are the best segment for backup:** ~3× the rate at the same home value.
- **Ranking inside a cell works** (ROC AUC ~0.65), so the product can go from an H3 map down to ordered doors.
- **An installer's own installs are weak validation.** Base Power's 229 Austin installs in 2026 fall where home
  value points, but installs also follow where the installer chose to sell.
- **Data gotchas that cost time:** StratMap blocks scripted downloads; its Tarrant file has every value at 0
  (Tarrant Appraisal District's own `ParcelView.zip` has values, living area and pools); 9 counties publish no
  land-use code (single-family inferred from values, lot size and legal description: 96% / 96% precision /
  recall against real codes in Collin); Dallas permits stop in 2020; Fort Worth's trade permits are 98% blank;
  permits at one address on the same day were deduplicated in a random order until fixed.

## 5. Plan vs what happened

| Plan item | What happened |
| --- | --- |
| Unit = block group, no household-level data (privacy) | Map stays on H3 res-8 **Cells**, and leads are ranked per home: the per-home test showed that's where the gain is. Privacy was set aside by decision on 2026-09-26. |
| LightGBM Poisson on ACS + parcel features | Built and tested; tied home value. Replaced by the home-value rule. |
| Beat income-only and a fit formula | Beat income-only easily; never beat home value alone. |
| Spatial CV, leave-one-city-out, temporal split | All three done, combined (train 2021-2023 on 4/5 of 5 km blocks, test 2024-2025 on the rest). The strict version with the 2017-2021 ACS vintage for training was built but not used; features came from ACS 2020-2024. |
| Training cities: Austin, Dallas, San Antonio, Fort Worth, Houston | Austin + San Antonio. Dallas stale, Fort Worth battery-only (validation), Houston not checked. |
| Base installs as validation | 229 in Austin 2026; weak evidence (sales targeting). |
| Installable share from parcels + footprints | Rules from Base's help center; footprints not built. |
| SHAP reasons, monotone constraints, untapped flag, neighbor-adoption features | Not done: pointless once the model tied one column. |
| DFW demo metro | 9 DFW counties scored, plus Austin, San Antonio and Houston metros: 3.9M homes, 22 counties. |
| Data freeze Saturday noon | Parcel scale-up ran until Saturday night. Risk #6 happened as predicted. |

## 6. How we worked (worth repeating)

- **Baselines before models**, and every model scored against them on the same held-out areas and years.
- **Out-of-sample by construction:** spatial blocks + time split + the other city, never random splits.
- **Measure the label before trusting it:** a gold set with an untouched test half, and two independent LLM
  labelers to show the gold labels themselves are reliable.
- **Cache every paid call** (Jev answers keyed by question version, model and permit text), so reruns are free.
- **Say when a result is weak:** the Base Power check and Fort Worth were reported as not validating the model
  rather than dropped.
