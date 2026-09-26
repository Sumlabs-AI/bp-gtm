"""Classify a permit into a lead category.

Keyword rules are conservative on purpose. Solar requires photovoltaic language or
a solar installation phrase (panel, array, system), so company names like
"Solar Turbines" or "SEG Solar" stay 'other'. EV requires an electric-vehicle
charging phrase. New homes are "new single family" / "new 1 family", plus
Houston's dotted new-dwelling abbreviation "S.F. RES" (not "SF RESIDENTIAL",
which is work on an existing house).
"""

import re

_SOLAR = re.compile(
    r"photovoltaic"
    r"|\bsolar\s+pv\b"
    r"|\bsolar\s+panels?\b"
    r"|\bsolar\s+arrays?\b"
    r"|\bsolar\s+systems?\b"
    r"|\bsolar\s+powers?\b"
    r"|\bsolar\s+permits?\b"
    r"|\bsolar\s+install"
    r"|\bpv\s+systems?\b",
    re.IGNORECASE,
)
_EV = re.compile(
    r"electric\s+vehicle|\bevse\b|\bev\s+charg|\bvehicle\s+charging\b",
    re.IGNORECASE,
)
# "S.F. RES" is how Houston labels a new single-family dwelling
# ("S.F. RES W/ATT. GARAGE"). The undotted "SF RESIDENTIAL ..." is a repair or addition.
_NEW_HOME = re.compile(
    r"\bnew\s+single[\s-]+family\b"
    r"|\bnew\s+1[\s-]+family\b"
    r"|\bnew\s+one[\s-]+family\b"
    r"|\bS\.F\.?\s*RES\b",
    re.IGNORECASE,
)


def classify(text: str) -> str:
    """Return solar, ev_charger, new_home, or other."""
    if not text or not text.strip():
        return "other"
    if _SOLAR.search(text):
        return "solar"
    if _EV.search(text):
        return "ev_charger"
    if _NEW_HOME.search(text):
        return "new_home"
    return "other"
