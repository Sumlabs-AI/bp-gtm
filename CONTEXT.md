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
Per-Cell prediction of battery adoption likelihood, owned by the ML workstream and built primarily from permit history. Answers "how likely is adoption here?", not "how needed is it?".
_Avoid_: adoption score, ML score, permit score

**Opportunity**:
The GTM interpretation of a Cell's Need Score together with its Propensity Score. Both dimensions stay visible; the combining formula is undefined until decided by the team.
_Avoid_: opportunity score (until a formula exists), priority

### Existing economics (ERCOT)

**Zone Economics Score**:
The existing per-Load-Zone battery economics score stored in `grid_zone_metrics`. An economics question at Load Zone level; not a Need Score.
_Avoid_: grid score, zone score, need
