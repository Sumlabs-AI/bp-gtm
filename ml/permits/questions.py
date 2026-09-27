"""Jev questions asked about every permit. One request per permit, all questions together.

Each question maps to one hand-labeled gold field (see permits/gold.py), so accuracy is
measured per question. Label rules that combine the answers live in permits/label.py.

Bump QUESTIONS_VERSION whenever wording changes: it keys the answer cache.
"""
from __future__ import annotations

import math

import pandas as pd
from typesafe_sdk import Choice, Noul

QUESTIONS_VERSION = "q2"

NAME_CAVEAT = (
    " Names of people, streets, subdivisions, or companies that merely contain a matching word"
    " (for example Franklin, Briggs, Kohler Street, Tesla Drive) do not count."
)

EQUIPMENT = {
    "standby_generator": Noul(
        instructions=(
            "Does this permit concern a permanently installed standby generator, meaning a fixed"
            " engine generator (for example Generac, Kohler, Cummins, Briggs & Stratton) that powers"
            " a building during outages? Count it when the permit installs, replaces, repairs, removes,"
            " or runs a gas line, pad, or wiring for such a generator. A permit that only says 'generator'"
            " or 'generator install' counts: permitted home generators are standby generators. Judge by"
            " `description`, not `permit_type`: San Antonio files generator work under 'Solar - Photovoltaic"
            " Permit'. Do not count portable generators connected through an inlet or interlock, or a"
            " mobile generator." + NAME_CAVEAT
        ),
    ),
    "portable_generator_hookup": Noul(
        instructions=(
            "Does this permit add a way to connect a portable generator to a home, such as a generator"
            " inlet box, an interlock kit, or a manual transfer switch for a portable generator?"
        ),
    ),
    "battery": Noul(
        instructions=(
            "Does this permit concern a home or building battery energy storage system (for example"
            " Tesla Powerwall, Enphase battery, FranklinWH, Generac PWRcell, Base Power, SolarEdge"
            " battery, or any 'ESS' / 'energy storage system')? Vehicle batteries, UPS units for"
            " computers, and battery-powered tools do not count." + NAME_CAVEAT
        ),
    ),
    "solar": Noul(
        instructions=(
            "Does this permit concern rooftop or ground-mounted solar panels (solar PV)? A permit type"
            " named 'Solar - Photovoltaic Permit' alone is not enough: the description must not point"
            " to different work, such as only a generator or only a battery."
        ),
    ),
    "panel_upgrade": Noul(
        instructions=(
            "Does this permit upgrade or replace the home's main electrical service or main panel,"
            " for example '100A to 200A upgrade', 'service upgrade', 'heavy up', 'main panel change'?"
        ),
    ),
    "ev_charger": Noul(
        instructions="Does this permit install an electric vehicle (EV) charger or a circuit for one?",
    ),
}

ACTION = Choice(
    instructions=(
        "What does this permit do to the main equipment it names in `description`? 'Request to"
        " disconnect', 'utility shutdown', or 'outage needed' mean a temporary power shutoff so the"
        " work can be done, not removal."
    ),
    criteria={
        "new_install": "Installs new equipment that was not there before.",
        "add_to_existing": "Adds equipment to an existing system, such as a battery added to existing solar.",
        "replace": "Replaces existing equipment with new equipment of the same kind.",
        "repair_or_service": "Repairs, services, or inspects existing equipment without installing new equipment.",
        "remove": "Removes or disconnects equipment without installing anything new.",
        "detach_reinstall": "Temporarily takes equipment off and puts it back, for example for a roof replacement.",
        "revision": "Revises, corrects, or renews an earlier permit rather than doing new work.",
        "supporting_work_only": (
            "Only supporting work for equipment covered elsewhere, such as a gas line, concrete pad,"
            " fence, or trenching for a generator."
        ),
        "cant_tell": "The text does not say what work is done, for example it is only a person's name.",
    },
)

PROPERTY = Choice(
    instructions="What kind of property is this permit for?",
    criteria={
        "single_family_home": "A detached single-family house, townhouse, duplex, or mobile home.",
        "multifamily": "An apartment or condo building with many units.",
        "commercial_or_public": (
            "A business, office, store, church, school, government site, cell tower, telecom site,"
            " or other non-residential property."
        ),
        "cant_tell": "The text does not say what kind of property it is.",
    },
)


def questions() -> dict:
    return {**EQUIPMENT, "action": ACTION, "property": PROPERTY}


def _clean(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v).strip()
    return s or None


def state(row: pd.Series | dict) -> dict:
    """Only what the questions need. No address, no valuation."""
    fields = {
        "permit_type": row.get("permit_type"),
        "work_class": row.get("work_class"),
        "permit_class": row.get("class_hint"),  # Austin: Residential / Commercial
        "description": row.get("description"),
        "contractor": row.get("contractor"),
    }
    return {k: c for k, v in fields.items() if (c := _clean(v)) is not None}
