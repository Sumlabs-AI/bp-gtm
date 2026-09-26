"""Keyword prefilter. Deliberately broad: the LLM handles precision, keywords only cut volume.

Recall of this filter is measured by sending a random sample of NON-matching permits
through the LLM too (source_row_kind == "recall_sample").
"""
import pandas as pd

KEYWORDS = {
    "kw_generator": r"GENERATOR|GENERAC|KOHLER|CUMMINS|BRIGGS|GENSET|STAND ?BY|TRANSFER SWITCH|\bATS\b|INTERLOCK|BACK ?UP POWER",
    "kw_battery": r"BATTER|POWER ?WALL|ENERGY STORAGE|\bESS\b|\bBESS\b|ENPHASE|ENCHARGE|FRANKLIN|PWRCELL|BASE POWER|STORAGE SYSTEM|\bKWH\b",
    "kw_solar": r"SOLAR|PHOTOVOLT|\bPV\b|\bPVS\b|ROOF ?MOUNT|MODULES",
    "kw_panel": r"SERVICE UPGRADE|SVC UPGRADE|PANEL UPGRADE|PANEL CHANGE|PANEL REPLAC|MAIN PANEL|UPGRADE.{0,20}\d{3} ?A|\d{3} ?AMP|HEAVY ?UP|METER ?BASE|SERVICE CHANGE",
    "kw_contractor": r"BASE POWER|TESLA|SUNRUN|GENERAC",
}

# Server-side SoQL LIKE patterns for Austin (superset; regex above re-applied locally).
AUSTIN_LIKE_TERMS = [
    "%GENERATOR%", "%GENERAC%", "%KOHLER%", "%CUMMINS%", "%TRANSFER SWITCH%", "% ATS%", "%STANDBY%",
    "%STAND BY%", "%INTERLOCK%", "%BACKUP POWER%", "%BACK UP POWER%",
    "%BATTER%", "%POWERWALL%", "%POWER WALL%", "%ENERGY STORAGE%", "% ESS%", "%BESS%", "%ENPHASE%",
    "%ENCHARGE%", "%FRANKLIN%", "%PWRCELL%", "%BASE POWER%", "%STORAGE SYSTEM%", "%KWH%",
    "%SOLAR%", "%PHOTOVOLT%", "% PV%", "%PV %",
    "%SERVICE UPGRADE%", "%SVC UPGRADE%", "%PANEL UPGRADE%", "%PANEL CHANGE%", "%PANEL REPLAC%",
    "%MAIN PANEL%", "%00 AMP%", "%00AMP%", "%00A %", "%HEAVY UP%", "%METER BASE%", "%SERVICE CHANGE%",
]


def keyword_flags(text: pd.Series) -> pd.DataFrame:
    up = text.fillna("").str.upper()
    return pd.DataFrame({k: up.str.contains(p, regex=True) for k, p in KEYWORDS.items()})
