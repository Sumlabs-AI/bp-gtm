"""Per-permit fields -> backup-install label.

Fields come from one of three sources, all in the same schema so they can be compared:
  - keyword_fields(): regex baseline (label v0, no API)
  - jev_fields():     Jev answers thresholded
  - gold labels:      hand labels (permits/gold.py)

backup_install() is the single rule that turns fields into the training label.
"""
from __future__ import annotations

import pandas as pd

EQUIPMENT = ["standby_generator", "portable_generator_hookup", "battery", "solar", "panel_upgrade", "ev_charger"]
# "cant_tell" counts: a permit that only names the equipment ("McDaniel - Battery") is almost always an install.
ADOPTION_ACTIONS = {"new_install", "add_to_existing", "cant_tell"}

_NAME_NOISE = r"FRANKLIN (?:HILLS|KYLE|PLUMBING)|BENJAMIN FRANKLIN|BRIGGS (?:SUMMIT|RANCH)|BATTERY (?:LANE|LN|ST)"

_EQUIP_RE = {
    "standby_generator": r"GENERATOR|GENERAC|KOHLER|CUMMINS|GENSET|STAN?DBY GEN|\d+ ?KW GEN",
    "portable_generator_hookup": r"INTERLOCK|INLET|PORTABLE GEN",
    "battery": r"BATTER|POWER ?WALL|ENERGY STORAGE|\bESS\b|\bBESS\b|ENCHARGE|FRANKLIN ?WH|PWRCELL|BASE POWER|STORAGE SYSTEM",
    "solar": r"SOLAR|PHOTOVOLT|\bPV\b",
    "panel_upgrade": r"SERVICE UPGRADE|SVC UPGRADE|PANEL UPGRADE|PANEL CHANGE|PANEL REPLAC|MAIN PANEL|HEAVY ?UP|UPGRADE.{0,20}\d{3} ?A|\d{3} ?AMP",
    "ev_charger": r"\bEV\b|CHARGER|CHARGING|ELECTRIC VEHICLE|WALL ?CONNECTOR",
}

_ACTION_RE = [  # first match wins
    ("detach_reinstall", r"DETACH|DE-?INSTALL|REMOVE (?:AND|&) REINSTALL|R ?& ?R\b|REINSTALL"),
    ("supporting_work_only", r"GAS LINE|GAS PIPING|GAS SERVICE|\bPAD\b ONLY|TRENCH"),
    ("remove", r"\bREMOV|DISCONNECT (?:AND|&) REMOVE|DECOMMISSION"),
    ("revision", r"REVISION|REVISE|CORRECTION|RENEW"),
    ("repair_or_service", r"\bREPAIR|REPLACE (?:THE )?(?:BREAKER|INVERTER|MODULE)|SERVICE CALL|TROUBLESHOOT"),
    ("replace", r"\bREPLAC|CHANGE ?OUT|SWAP"),
    ("add_to_existing", r"(?:TO|ON) (?:AN )?EXIST|ADD(?:ING|ITION)? .{0,30}(?:BATTER|STORAGE)|\+ ?BATTERY"),
    ("new_install", r"INSTALL|NEW|ADD|\d+ ?KW"),
]

_PROPERTY_RE = [
    ("multifamily", r"APARTMENT|\bAPTS?\b|CONDO|MULTI-?FAMILY|\bUNITS?\b \d"),
    ("commercial_or_public", r"COMMERCIAL|CHURCH|SCHOOL|AT ?& ?T|VERIZON|T-MOBILE|\bSBA\b|TOWER|TELECOM|OFFICE|STORE|RESTAURANT|HOSPITAL|CITY OF|WAREHOUSE|\bLLC\b SITE"),
    ("single_family_home", r"RESIDENCE|RESIDENTIAL|\bSFR?\b|SINGLE FAMILY|HOME|HOUSE|DUPLEX|TOWNHOME|RES\b"),
]


def _text(df: pd.DataFrame) -> pd.Series:
    return (df["description"].fillna("") + " | " + df["permit_type"].fillna("")).str.upper()


def _code_rules(out: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """Rules that hold regardless of the text source.

    Plumbing / gas permits never count as the install: the generator's electrical permit
    does, so counting both would double count.
    """
    plumbing = df["permit_type"].fillna("").str.contains(r"PLUMBING|\bGAS\b", case=False, regex=True)
    out.loc[plumbing, "action"] = "supporting_work_only"
    return out


def keyword_fields(df: pd.DataFrame) -> pd.DataFrame:
    t = _text(df).str.replace(_NAME_NOISE, " ", regex=True)
    out = pd.DataFrame(index=df.index)
    for k, p in _EQUIP_RE.items():
        out[k] = t.str.contains(p, regex=True)
    # "Solar - Photovoltaic Permit" is SA's catch-all for generator/battery work too.
    desc = df["description"].fillna("").str.upper()
    only_type_says_solar = ~desc.str.contains(_EQUIP_RE["solar"]) & (out["standby_generator"] | out["battery"])
    out.loc[only_type_says_solar, "solar"] = False

    out["action"] = "cant_tell"
    for label, p in reversed(_ACTION_RE):
        out.loc[t.str.contains(p, regex=True), "action"] = label

    out["property"] = "cant_tell"
    for label, p in reversed(_PROPERTY_RE):
        out.loc[t.str.contains(p, regex=True), "property"] = label
    cls = df.get("class_hint")
    if cls is not None:
        out.loc[(out["property"] == "cant_tell") & (cls == "Residential"), "property"] = "single_family_home"
        out.loc[(out["property"] == "cant_tell") & (cls == "Commercial"), "property"] = "commercial_or_public"
    return _code_rules(out, df)


def jev_fields(df: pd.DataFrame, yes: float = 0.5) -> pd.DataFrame:
    """Jev answers (from permits.jev.run) -> the same schema. Thresholds are tuned on gold."""
    out = pd.DataFrame(index=df.index)
    for k in EQUIPMENT:
        out[k] = df[f"p_{k}"] >= yes
    out["action"] = df["action"]
    out["property"] = df["property"]
    cls = df.get("class_hint")
    if cls is not None:
        out.loc[(out["property"] == "cant_tell") & (cls == "Residential"), "property"] = "single_family_home"
    return _code_rules(out, df)


def backup_install(f: pd.DataFrame) -> pd.Series:
    """The training label: a residential adoption of a standby generator or a home battery.

    "cant_tell" property counts as residential: residential dominates both cities' candidates,
    and San Antonio descriptions rarely say. Supporting work (gas lines) is excluded so a
    generator with separate electrical + plumbing permits is not double counted.
    """
    equipment = f["standby_generator"] | f["battery"]
    adoption = f["action"].isin(ADOPTION_ACTIONS)
    residential = f["property"].isin({"single_family_home", "cant_tell"})
    return equipment & adoption & residential
