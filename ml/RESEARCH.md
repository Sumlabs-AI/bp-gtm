# Propensity research log

What we tried to predict who buys backup power, what each test showed, and what we decided. Written
2026-09-26. The decision itself is [ADR 0002](../docs/adr/0002-propensity-home-value-rule.md); commands, file
layout and the full result tables are in [README.md](README.md).

**Outcome in one line:** the machine-learning research was **not conclusive**. No model beat a single number,
the home's appraised value. Propensity is therefore a transparent rule (appraised value, doubled for homes that
already have solar, ranked within the metro), and the ML work is stopped.

## 1. Question and label

- **Question:** which homes (and which areas) are most likely to buy residential backup power?
- **Label:** a built backup install (standby generator or battery) on a single-family home, from city permit
  descriptions classified by Jev (gold test accuracy 92.9%, precision 89.5%, recall 82.9%). Austin and San
  Antonio, 2021-2025. Base Power's own permits are excluded from the label.
- **Why these years:** San Antonio's data starts Dec 2020 and 2026 is partial. Winter Storm Uri (Feb 2021)
  inflates 2021; a per-year label allowed a check without it.
- **Why only two cities:** permits only help if trade (electrical / plumbing) permits carry a description,
  because that is where generators are filed. Dallas' open data stops in mid-2020. Fort Worth publishes
  descriptions only on building permits (see §5).

## 2. How every test was scored

- **Out of sample in space and time:** train on 2021-2023 installs in 4/5 of the area (5 km grid blocks),
  rank the held-out fifth, check where the 2024-2025 installs happened. A score must work on places it has
  never seen, because most of Texas has no permit data.
- **Leave one city out:** train on Austin, rank San Antonio, and the reverse. The closest thing to scoring a
  metro with no permits.
- **Ranking metrics only:** propensity is used to order doors, not to forecast sales.
  - Area level: *capture AUC* (count version of ROC AUC, weighted by homes; 0.5 random, 1 perfect) and the share
    of installs in the top 20% of homes.
  - Home level: ROC AUC (installed or not) and the share of installers in the top 10% / 20% of homes.
  - A plain ROC AUC on "block group had ≥ 1 install" was rejected: it rewards big block groups.
- **Every model is compared with simple baselines**: area home value, area income, past installs, random.

## 3. Experiments, in order

### 3.1 Block-group model on Census features (not conclusive)

1,313 block groups ≥ 90% inside Austin or San Antonio, 24 ACS features, LightGBM Poisson with eligible homes
as exposure and a per-city offset (Austin installs at 7× San Antonio's rate, partly permit practice).

| Held-out area, 2024-2025 installs | Austin capture AUC / top 20% | San Antonio capture AUC / top 20% |
| --- | --- | --- |
| LightGBM | 0.68 / 45% | 0.77 / 60% |
| Poisson GLM, 7 features | 0.68 / 44% | 0.77 / 58% |
| area home value alone | 0.69 / 44% | 0.77 / 59% |
| past installs 2021-2023 | 0.69 / 46% | 0.71 / 55% |
| random | 0.50 / 20% | 0.50 / 20% |

- The signal is real (2-3× random), but **no model beat home value alone**.
- Leave one city out: LightGBM 0.62 / 0.71, GLM 0.69 / 0.76, home value 0.68 / 0.75. **The trees do not transfer
  between cities**; the GLM does, and only matches home value.
- Model and home-value rankings correlate at 0.75 and share two-thirds of their top-20% block groups. A 50/50
  blend adds +0.005 to +0.012 AUC. Nothing worth claiming.
- **Fix made along the way:** ACS undercounts eligible homes in mixed block groups, which taught the model a
  spurious "more single-family → fewer installs" effect. Parcel counts as exposure removed most of it.

### 3.2 emPOWER, electricity-dependent Medicare residents (negative)

Added per ZIP to the block-group model (`train/empower.py`). Negative correlation with installs, mostly home value
in disguise; no model improvement; the trees learned ZIP identity and transferred worse. Medical need belongs in
the Need layer, not propensity.

### 3.3 Home level: per-home appraised value (the finding that changed the plan)

336k owner-occupied single-family parcels (Travis, Bexar); 85-88% of install permits land on one of them.

| Held-out homes, 2024-2025 installers | Austin ROC AUC / top 20% | San Antonio ROC AUC / top 20% |
| --- | --- | --- |
| area home value (Census block-group median) | 0.70 / 43% | 0.78 / 59% |
| **home's own appraised value** | **0.76 / 58%** | **0.82 / 69%** |
| LightGBM, home features (value, year built, lot, sq ft, stories, deed year) | 0.75 / 54% | 0.82 / 69% |
| LightGBM, home + area features | 0.75 / 54% | 0.82 / 67% |

- **Per-home value beats area value by 10-15 points** of installers found in the top 20%. About two-thirds of the
  gain is resolution (the home instead of the area), one-third a better source (appraisal instead of survey).
- The relationship is monotone and accelerating: Austin installs per 1,000 homes go from 3.3 (cheapest tenth) to
  67 (top tenth) and 125 (top 1%).
- **LightGBM with every other home attribute only ties the single value column.**
- Ranking *inside* one block group or H3 res-8 cell works (ROC AUC ~0.65); an area score is 0.50 there.

### 3.4 Permit history on the home

- **Solar (tested, kept):** at the same home value, homes with a solar permit dated 2023 or earlier added backup
  ~3× more often in Austin (e.g. top value quintile 15.7 → 41.4 per 1,000). Rule "value doubled if solar":
  Austin ROC AUC 0.766 / top 20% 59%, the best of anything tested, above every LightGBM variant (0.760-0.762).
  San Antonio unchanged (only 11 of 156 test installers had solar).
- **EV chargers (tried, inconclusive):** 76 homes in Austin, 3 in San Antonio. The permit download only searched
  generator / battery / solar / panel keywords, so EV permits came in by accident. Too few to read.
- **Panel upgrades (tried, inconclusive):** too few and no consistent direction.
- **Pools (tried, inconclusive):** only Tarrant publishes pools (Tarrant Appraisal District). Its only label is
  Fort Worth batteries, which are solar sales (§5); there pools went in opposite directions by value band. Pools
  have **not** been tested against real backup buyers.

### 3.5 Validation attempts that did not work

- **Fort Worth as a third city:** 97% of its battery permits are bundled with solar and generators are invisible
  (9 vs 686). Nothing ranks these buyers: area models, home value, per-home value (ROC AUC 0.50), LightGBM (0.54).
  Their profile is newer, mortgaged, middle-income homes. **Solar + storage is a different buyer from backup
  power**, so Fort Worth cannot validate a backup propensity.
- **Base Power's 2026 installs (229 in Austin):** they fall where home value points (capture AUC 0.68-0.69), but
  where an installer's customers are also reflects where it chose to sell, so this cannot separate demand from
  sales targeting. Recorded as weak evidence only.

## 4. Decision

- **Propensity = log(appraised value) + log(2) if the home has a solar permit, ranked as a percentile within its
  metro.** Homes that already have a backup permit are not ranked (not leads). Where no appraisal exists, the
  block group's Census median value is used and flagged.
- **Cell score** (H3 res 8) = aggregate of its homes' percentiles; homes inside a cell are ranked by the same rule.
- **ML research stops.** The code stays as the test bench: any future score must beat this rule on the same
  held-out tests before replacing it.

Why a rule rather than the tied model: equal accuracy, but it transfers to metros without permits (the trees did
not), a rep or a Base engineer can check it in one sentence, and it needs one field that every appraisal district
publishes.

## 5. Caveats

- **The ×2 solar factor was chosen on the same test period** (×2, ×3 and ×4 were within 0.004 AUC in Austin, so
  it is barely tuned). Check it on 2026 installs as they come in.
- **Solar is known only inside Austin and San Antonio city limits** (~19k homes). Everywhere else the rule is home
  value alone. Harris appraisal data records solar per home and could extend it.
- **Owner-occupied** is the homestead exemption only in Bexar; elsewhere mailing address = property address.
- **Single-family in 9 counties without land-use codes** comes from a value rule (house worth ≥ $30k on a
  house-sized lot, not a condo): 96% / 96% precision / recall against real codes in Collin, 90% / 93% in Denton.
- **Appraisals are a 2025-2026 snapshot**, so a 2024-2025 install could slightly raise its own home's value (a few
  percent for a generator), small next to the gaps above.
- **Label limits:** city limits only; generators and batteries from any installer; Jev recall 83%.

## 6. What would reopen the ML question

1. **A better label**: Base's own installs at scale, or sales outcomes (doors knocked → sold), which measure the
   exact product and remove the city-permit limits.
2. **Per-home attributes an appraisal value doesn't carry**, tested against backup buyers: pools in Harris (HCAD
   extra features, with Harris / Houston permits), EV-charger permits fetched directly (Austin publishes them),
   household electricity use.
3. **More permit cities with described trade permits**, to test transfer beyond two cities.

Not tried, because the gap to the single column was too small to justify them: hyperparameter search, other
algorithms, class-weighted classifiers at home level.
