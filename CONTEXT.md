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
An ERCOT settlement/load zone (LZ_HOUSTON, LZ_NORTH, LZ_SOUTH, LZ_WEST, LZ_AEN, LZ_CPS, …). Each Cell is assigned the Load Zone its center falls in; Cell and Load Zone remain different levels of geography.
_Avoid_: zone (unqualified), market

### Need

**Need Score**:
Per-Cell measure of how useful/necessary battery backup is in that geography. Composed from explainable Need Components.
_Avoid_: score (unqualified), risk score

**Baseline Need**:
Long-term structural Need for a Cell, driven by historical outage, weather and resilience exposure. Changes slowly. Historical events (e.g. past Major Outage Events) explain Baseline Need; they never answer "why now".
_Avoid_: static need, historical need

**Live Need**:
Current/near-term urgency for a Cell, driven by active alerts, forecasts, current outages and current ERCOT conditions. Changes rapidly. Answers "why now?".
_Avoid_: current need, real-time need, urgency

**Need Signal**:
A human-readable reason attached to a Cell's Need (e.g. "Severe weather expected within 24 hours"). Explains Need; not Lead Evidence.
_Avoid_: alert, reason

**Outage Need Component**:
The outage-derived part of Need Score: the mean of Observed Outage Exposure and Utility Reliability Need, or whichever of the two exists.
_Avoid_: outage score

**Observed Outage Exposure**:
How much outage a Cell's county has actually experienced: the Texas percentile of outage hours per customer over 5 years. County-level: every Cell in a county shares it. Outage Events and Major Outage Events explain that history but are not scored.
_Avoid_: outage history score, outage risk

**Utility Reliability Need**:
How unreliable a Cell's electric utility is in normal conditions (interruption minutes per customer, excluding major events), as a Texas percentile. Unknown where the Cell's utility is unknown.
_Avoid_: utility score, reliability score

**Outage Event**:
A continuous period in which a meaningful share of a county's customers are without power. A **Major Outage Event** is one whose peak share or total customer-hours crosses the major threshold.
_Avoid_: outage (when meaning the county-level event), storm

**Reference Population**:
The set a raw metric is ranked against to make a 0–100 percentile: all Texas counties or all Texas utilities with usable data, not just our Markets.
_Avoid_: benchmark, peer group

**Data Through**:
The last date an external source's history covers. Features computed from that source are "as of" this date, never implied to be current.
_Avoid_: last updated, as of today

**Weather Need Component**:
The weather-derived part of Need Score. Baseline: Storm Exposure and Temperature Extremes Exposure over history. Live (later): active alerts and forecast extremes.
_Avoid_: weather score

**Storm Exposure**:
How often a place falls under warnings for frequent outage-causing storms (severe thunderstorm, tornado, extreme wind), counted in warning-days, as a Texas percentile. Part of the Weather Need Component; varies within a county. Rare tropical and ice events are not in it (they appear through outage history, and later in Live Need).
_Avoid_: storm risk, storm score

**Temperature Extremes Exposure**:
How often a place measurably reaches heat or cold that makes an outage dangerous (days ≥ 100°F, days ≤ 28°F), as a Texas percentile. Part of the Weather Need Component. Measured temperature, not NWS advisories, and without humidity.
_Avoid_: heat score, climate risk

**Warning-day**:
A local calendar day on which a place was inside at least one qualifying NWS warning area. Counting days, not warnings, keeps one storm with several warnings from counting several times.
_Avoid_: warning count (when meaning days)

**Live Weather Signal**:
Umbrella for evidence that weather makes backup power urgent now. It has exactly two kinds, NWS Alerts and Forecast Signals, which must never be presented as equivalent. Not a score.
_Avoid_: live alert (for both kinds), weather event

**NWS Alert**:
An official NWS warning, watch or advisory (e.g. a Tornado Warning), issued by NWS with its own area and event time window. High-confidence, actionable.
_Avoid_: alert signal, warning (for watches/advisories too)

**Forecast Signal**:
Our deterministic reading of NWS gridded forecast or SPC outlook data: a continuous period in which a forecast value crosses one of our thresholds (e.g. wind gusts ≥ 58 mph from 14:00 to 20:00 tomorrow), or an SPC risk area. Derived by us, not issued by NWS.
_Avoid_: forecast alert, warning, prediction

**Active** (signal):
A Live Weather Signal that currently counts, judged at read time. An NWS Alert is Active when its time window contains now and it was in the latest successful Snapshot. A Forecast Signal is Active when it hasn't ended, starts within the next 48 hours, and hasn't been replaced by a newer successful forecast for its point. A Cell is affected when its center is inside the area (alerts) or it belongs to the signal's forecast point (forecasts).
_Avoid_: current, open

**Snapshot**:
One complete fetch of all active NWS Alerts for Texas. Only a successful, complete Snapshot can end alerts that disappeared; a failed one changes nothing, and alert data becomes stale when no Snapshot has succeeded recently.
_Avoid_: poll (when meaning the stored result), sync

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
Estimated annual energy-arbitrage value ($/yr) of a battery size in a Lead's Load Zone, from the Zone Economics backtest.
_Avoid_: value (unqualified), savings

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
