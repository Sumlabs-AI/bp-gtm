"""Lead scoring assumptions. Not secrets, so they live in code (like app/grid/config.py).
Re-run `python -m app.leads score` after changing them."""

from pydantic import BaseModel

# TDSPs whose customers can choose Base as their retail provider (basepowercompany.com,
# checked 2026-09-26). Co-ops Base also serves (CoServ, GVEC, Farmers) aren't in the
# ERCOT ESI ID extract, so they need another eligibility source later.
BASE_TDSPS = {"centerpoint", "oncor", "aep_central", "aep_north", "tnmp"}

# Utilities Base serves through a partnership whose meters aren't in the ERCOT ESI ID extract
# (municipal utilities don't file it): a home whose parcel point falls in the load zone is
# eligible without a meter match. Austin Energy's territory is its own zone, LZ_AEN.
PARTNER_UTILITY_ZONES = {"LZ_AEN": "austin_energy"}


# Rough ERCOT load zone per TDSP, used only when a lead has no map point.
TDSP_ZONES = {
    "centerpoint": "LZ_HOUSTON",
    "oncor": "LZ_NORTH",  # Oncor also serves parts of LZ_WEST
    "aep_central": "LZ_SOUTH",
    "aep_north": "LZ_WEST",
}


class LeadScoringConfig(BaseModel):
    # Signals older than this don't count (permit issued / owner changed).
    signal_lookback_days: int = 3 * 365
    # A home built within this many years counts as new construction.
    new_home_years: int = 2
    # "New this week" window for triggers.
    new_window_days: int = 7
    weights: dict[str, float] = {
        "home_size": 0.20,
        "solar": 0.20,
        "ev_charger": 0.15,
        "new_owner": 0.15,
        "home_value": 0.10,
        "new_home": 0.10,
        "pool": 0.10,  # pools/spas: large, steady electric load
    }
    # Drivers a county's appraisal data can't tell: left out of those leads' score (the other
    # weights are rescaled), not counted as 0. Travis' public layer has no living area or pools.
    unknown_drivers: dict[str, set[str]] = {"travis": {"home_size", "pool"}}
    # Battery we'd pitch, by heated area (sqft upper bounds); a pool bumps it one size up.
    battery_sizing: list[tuple[float, int]] = [(2_500, 25), (4_000, 40), (float("inf"), 50)]


scoring = LeadScoringConfig()
