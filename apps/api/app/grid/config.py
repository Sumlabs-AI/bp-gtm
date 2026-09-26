"""Model assumptions for the grid economics engine.

These are not secrets, so they live in code rather than .env. Edit the defaults here
(then re-run `python -m app.grid compute`) to change the analysis.
"""

from pydantic import BaseModel


class BatteryConfig(BaseModel):
    # Base home battery as described in the hackathon plan; power and efficiency are
    # assumptions, not published specs.
    capacity_kwh: float = 39.2
    power_kw: float = 11.5
    round_trip_efficiency: float = 0.90


class ScoringConfig(BaseModel):
    lookback_days: int = 365
    # Real-time price at or above which an interval counts as scarcity ($/MWh).
    scarcity_threshold: float = 1000.0
    # Hours used for the "typical daily spread" (top N hours minus bottom N hours).
    spread_hours: int = 4
    # Relative weight of each driver in the Grid Value Score. Normalized at use.
    weights: dict[str, float] = {
        "arbitrage": 0.40,
        "congestion": 0.20,
        "scarcity": 0.15,
        "surprise": 0.15,
        "negative_prices": 0.10,
    }


battery = BatteryConfig()
scoring = ScoringConfig()
