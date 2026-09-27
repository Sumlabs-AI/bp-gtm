# Propensity

Who is likely to buy backup power. Per home, then per **Cell** (H3 res 8). Terms: [`CONTEXT.md`](../CONTEXT.md).
Decision: [ADR 0002](../docs/adr/0002-propensity-home-value-rule.md). Full research log: [`ml/RESEARCH.md`](../ml/RESEARCH.md).
How we got here (process, data workstreams, discoveries): [research-process.md](research-process.md).

## The rule

```text
score = log(appraised value) + log(2) if the home has a solar permit
propensity = percentile of score within the home's metro
```

- **Homes:** owner-occupied single-family parcels. Homes with a backup permit already (generator, battery, Base
  Power) are flagged `has_backup` and not ranked.
- **No appraisal:** the block group's Census median value is used instead (`value_source = acs_block_group`).
- **Solar** is known only inside Austin and San Antonio city limits (permit data); elsewhere the rule is value alone.
- **Cell:** aggregated from its homes; the same rule orders the homes inside a Cell.

It is a rule, not a trained model: the ML research was **not conclusive** (no model beat the home's value).

## Why (headline results)

Held out in space and time: learn on 2021-2023, check who installed backup in 2024-2025 in areas not used.

| Score | Austin: share of buyers in top 20% of homes | San Antonio |
| --- | --- | --- |
| Area home value (Census block-group median) | 43% | 59% |
| **Home's own appraised value** | **58%** | **69%** |
| LightGBM on every parcel attribute | 54% | 67-69% |
| Value doubled if solar (the rule) | 59% | 68% |
| Random | 20% | 20% |

- Block-group models on Census features (LightGBM, Poisson GLM) only tied area home value; LightGBM also failed
  when trained on one city and tested on the other.
- Solar owners bought backup ~3× more often at the same home value (Austin).
- Ranking inside one Cell works (ROC AUC ~0.65 vs 0.50 for any area-level score).

## Open

- Pools and EV chargers: tried, inconclusive (too few EV permits; pools only testable on Fort Worth solar buyers).
- The ×2 solar factor was chosen on the test period: recheck on 2026 installs.
- Reopen ML with a better label (Base's own installs at scale, sales outcomes): `ml/RESEARCH.md` §6.

## Data and commands

- **Parcels:** 22 counties (Austin, San Antonio, DFW, Houston metros): TxGIO StratMap zips, Travis and Bexar county
  services, Tarrant Appraisal District. Download links, the single-family rule for counties without land-use codes,
  and per-county checks: [`ml/README.md`](../ml/README.md) ("Home scores").
- **Build** (from `ml/`, see `ml/README.md` for the steps before these):

```bash
uv run python -m parcels.normalize
uv run python -m score.homes   # -> data/processed/home_scores.parquet, h3_scores.parquet
```

- **Into the app:** Cell scores are exported and imported per [ml-contract.md](ml-contract.md).
- **Benchmark:** `uv run python -m train.homes` reruns the home-level comparison; a new score must beat the rule there.
