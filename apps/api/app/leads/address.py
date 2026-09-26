"""Address normalization used to join meters, permits and appraisal records.

Different sources write the same address differently ("123 North Oak Street",
"123 N OAK ST", "123 N. Oak St., Unit 2"). We reduce each to a key:

    "<house number> <street tokens> <zip5>"   e.g. "123 N OAK ST 77002"

Only for single-family matching: unit designators are dropped.
"""

import re

SUFFIXES = {
    "STREET": "ST",
    "STR": "ST",
    "AVENUE": "AVE",
    "AV": "AVE",
    "DRIVE": "DR",
    "DRV": "DR",
    "ROAD": "RD",
    "LANE": "LN",
    "COURT": "CT",
    "CIRCLE": "CIR",
    "BOULEVARD": "BLVD",
    "PLACE": "PL",
    "TRAIL": "TRL",
    "PARKWAY": "PKWY",
    "PKY": "PKWY",
    "HIGHWAY": "HWY",
    "TERRACE": "TER",
    "COVE": "CV",
    "WAY": "WAY",
    "LOOP": "LOOP",
    "BEND": "BND",
    "CROSSING": "XING",
    "HOLLOW": "HOLW",
    "MEADOWS": "MDWS",
    "POINT": "PT",
    "RIDGE": "RDG",
    "SQUARE": "SQ",
    "FREEWAY": "FWY",
    "EXPRESSWAY": "EXPY",
    "GLEN": "GLN",
    "HEIGHTS": "HTS",
    "PASS": "PASS",
    "PATH": "PATH",
    "RUN": "RUN",
    "VIEW": "VW",
    "VISTA": "VIS",
    "PARK": "PARK",
    "ROW": "ROW",
    "SPRINGS": "SPGS",
    "CREEK": "CRK",
    "ESTATES": "ESTS",
    "GROVE": "GRV",
    "HILLS": "HLS",
}
DIRECTIONS = {
    "NORTH": "N",
    "SOUTH": "S",
    "EAST": "E",
    "WEST": "W",
    "NORTHEAST": "NE",
    "NORTHWEST": "NW",
    "SOUTHEAST": "SE",
    "SOUTHWEST": "SW",
}
UNIT_WORDS = {"APT", "APARTMENT", "UNIT", "STE", "SUITE", "BLDG", "LOT", "SPC", "#"}


def zip5(value: object) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[:5] if len(digits) >= 5 else None


def normalize_street(street: str | None) -> str | None:
    if not isinstance(street, str) or not street:  # also rejects pandas NaN
        return None
    s = re.sub(r"[^\w# ]", " ", street.upper().replace("#", " # "))
    tokens = s.split()
    out: list[str] = []
    for tok in tokens:
        if tok in UNIT_WORDS:
            break  # everything after a unit designator is the unit
        out.append(SUFFIXES.get(tok) or DIRECTIONS.get(tok) or tok)
    # Must start with a house number (allow e.g. "123A").
    if not out or not re.match(r"^\d+[A-Z]?$", out[0]):
        return None
    return " ".join(out)


def address_key(street: str | None, zip_code: object) -> str | None:
    street_norm = normalize_street(street)
    z = zip5(zip_code)
    if not street_norm or not z:
        return None
    return f"{street_norm} {z}"
