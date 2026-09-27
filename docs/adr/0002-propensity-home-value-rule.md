# 2. Propensity is a home-value rule, not a trained model

Date: 2026-09-26 · Status: accepted

## Context

The plan was a LightGBM model trained on city permit history (backup installs in Austin and San Antonio,
2021-2025) to produce the **Propensity Score** per **Cell**. The research is in [`ml/RESEARCH.md`](../../ml/RESEARCH.md).
In short:

- At block-group level, LightGBM and a Poisson GLM on 24 Census features only tied the block group's median home
  value (capture AUC 0.68 / 0.77 vs 0.69 / 0.77), and LightGBM did worse on a city it was not trained on.
- At home level, the home's own appraised value beat the area value (top 20% of homes: 58% vs 43% of 2024-2025
  installers in Austin, 69% vs 59% in San Antonio). LightGBM with every other parcel attribute tied it.
- Homes with a solar permit bought backup ~3× more often at the same value; "value doubled if solar" was the best
  score tested in Austin (ROC AUC 0.766 vs LightGBM 0.760-0.762).
- The one extra validation city available (Fort Worth) only shows solar-plus-battery sales, which nothing ranks,
  so it cannot validate a backup model.

The ML research was not conclusive: no model beat a single column.

## Decision

- **Per home:** score = log(appraised value) + log(2) if the home has a solar permit, ranked as a percentile within
  its metro. Homes with a backup permit already are not ranked. Without an appraisal, the block group's Census
  median value is used and flagged (`value_source`). Code: `ml/score/homes.py`.
- **Per Cell:** aggregated from its homes; the same rule orders the homes inside a Cell.
- **Stop the ML research.** The training and evaluation code (`ml/train/`) stays as the benchmark any future model
  must beat on the same held-out tests.

## Alternatives

- **LightGBM (block group or home):** same accuracy, does not transfer between cities, harder to explain.
- **Poisson GLM:** transfers, same accuracy as home value alone, adds nothing a rep can use.
- **Area home value from the Census:** available statewide without parcels, but 10-15 points worse than per-home
  value. Kept only as the fallback.

## Consequences

- Propensity needs parcel data (appraised value) for every county scored: 22 counties across Austin, San Antonio,
  DFW and Houston are loaded (`ml/README.md`, "Home scores").
- **Glossary change:** `CONTEXT.md` defines the Propensity Score as "produced by the ML workstream from permit
  history and static Need features". It should read: produced by the home-value rule above from parcel appraisals
  and solar permits; no Need features are used. `model_version` names the rule (`home-value-solar-v1`).
- The **Lead Score** (`apps/api/app/leads/config.py`) weights home value at 10%, below home size, solar, EV and new
  owner. The research supports home value as the dominant driver and solar as a bonus; the other drivers were not
  shown to add anything. Re-weighting it is a separate decision.
- Reopen when a better label exists (Base's own installs at scale, or sales outcomes) or per-home attributes can be
  tested against backup buyers (pools, EV chargers, electricity use): `ml/RESEARCH.md` §6.
