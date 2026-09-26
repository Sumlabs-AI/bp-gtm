# Base GTM Intelligence

GTM intelligence for Base Power Company: where residential battery backup is needed (Need), where people are likely to adopt it (Propensity), and where those overlap (Opportunity). Geography is normalized onto H3 cells so independent signals can be joined.

## Language

### Geography

**Cell**:
An H3 resolution-8 hexagon, identified by its `h3_index` string. The canonical unit at which Need and Propensity are computed and joined.
_Avoid_: grid cell, hex, hexagon, tile

**Market**:
A named geographic area (e.g. Harris, Travis) used to decide which Cells are seeded. Not an ERCOT market and not a unit of computation.
_Avoid_: region, area, county (when meaning the seed area)

**Load Zone**:
An ERCOT settlement/load zone (LZ_HOUSTON, LZ_NORTH, LZ_SOUTH, LZ_WEST, LZ_AEN, LZ_CPS, …). A Cell may intersect a Load Zone; they are different levels of geography.
_Avoid_: zone (unqualified), market

### Need

**Need Score**:
Per-Cell measure of how useful/necessary battery backup is in that geography. Composed from explainable Need Components.
_Avoid_: score (unqualified), risk score

**Baseline Need**:
Long-term structural Need for a Cell, driven by historical outage, weather and resilience exposure. Changes slowly.
_Avoid_: static need, historical need

**Live Need**:
Current/near-term urgency for a Cell, driven by active alerts, forecasts, current outages and current ERCOT conditions. Changes rapidly. Answers "why now?".
_Avoid_: current need, real-time need, urgency

**Need Signal**:
A human-readable reason attached to a Cell's Need (e.g. "Severe weather expected within 24 hours"). Explains Need; not Lead Evidence.
_Avoid_: alert, reason

**Outage Need Component**:
The outage-derived part of Need Score (frequency, duration, recency, customers affected).
_Avoid_: outage score

**Weather Need Component**:
The weather-derived part of Need Score (historical severe weather, active alerts, forecast extremes).
_Avoid_: weather score

**Grid Need Component**:
The ERCOT-derived part of Need Score (load, capacity, forecast load, resource outages, prices). Only signals that indicate value/urgency for residential storage belong here.
_Avoid_: grid score, grid component, grid stress score

### Propensity and Opportunity

**Propensity Score**:
Per-Cell prediction of battery adoption likelihood, owned by the ML workstream and built primarily from permit history. Answers "how likely is adoption here?", not "how needed is it?". Not yet built; distinct from Lead Score.
_Avoid_: adoption score, ML score, permit score, lead score

**Opportunity**:
The GTM interpretation of a Cell's Need Score together with its Propensity Score. Both dimensions stay visible; the combining formula is undefined until decided by the team.
_Avoid_: opportunity score (until a formula exists), priority, expected value

### Leads

**Lead**:
An eligible property (single-family, owner-occupied, on an active residential meter of a utility Base serves). A property, not a person.
_Avoid_: prospect, customer, contact

**Lead Score**:
Per-Lead heuristic fit score (0–100) from weighted, explainable drivers such as home size, value, solar, pool and new owner. Rule-based lead qualification; not the ML Propensity Score and not a Need Score.
_Avoid_: propensity, fit score (in docs), score (unqualified)

**Lead Evidence**:
A dated fact supporting a Lead's drivers or trigger (a permit, a new meter, an appraisal flag).
_Avoid_: signal (reserved for Need Signal)

**Trigger**:
The latest Lead Evidence that makes a Lead worth a fresh look this week (new permit, new meter, new owner, newly eligible).
_Avoid_: alert, event

**Grid Value**:
Estimated annual energy-trading value ($/yr) for a battery size in a Lead's Load Zone in an average full calendar year (2019 onward, matching multi-year contracts), modeled using day-ahead plans without hindsight, after losses, wear and backup reserve (Zone Economics backtest). Shown alongside the last 12 months, the lowest/highest full year and its **Grid Value Ceiling**. Falls back to the last 12 months when no full-year history is loaded.
_Avoid_: value (unqualified), savings, revenue

**Grid Value Ceiling**:
The most a battery size could have earned in the Load Zone over the same period (an average full year) with perfect knowledge of every price. A benchmark for Grid Value, never a sales figure.
_Avoid_: potential, max revenue

**Expected Value**:
Lead Score / 100 × Grid Value of the recommended battery size; the default Lead ranking. A per-Lead economics ranking, not Opportunity.
_Avoid_: priority score, opportunity

**Lead Cluster**:
A map-only aggregation of nearby Leads shown when too many are in view. Not a Cell.
_Avoid_: grid cell, cell, bucket

### Existing economics (ERCOT)

**Zone Economics Score**:
The existing per-Load-Zone battery economics score stored in `grid_zone_metrics`. An economics question at Load Zone level; not a Need Score.
_Avoid_: grid score, zone score, need
