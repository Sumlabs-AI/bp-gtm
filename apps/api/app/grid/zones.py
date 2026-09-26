"""ERCOT settlement points we track, with plain-language descriptions."""

from dataclasses import dataclass

# Every zone is compared against this system-wide reference price.
REFERENCE_HUB = "HB_HUBAVG"


@dataclass(frozen=True)
class Zone:
    code: str
    name: str
    description: str
    # False for zones without a contiguous geography (shown in lists, not on the map).
    on_map: bool = True


ZONES = [
    Zone("LZ_HOUSTON", "Houston", "Greater Houston and the Gulf Coast (CenterPoint area)."),
    Zone("LZ_NORTH", "North", "Dallas–Fort Worth and North/Central Texas (mostly Oncor)."),
    Zone("LZ_SOUTH", "South", "South Texas, Corpus Christi and the Rio Grande Valley."),
    Zone("LZ_WEST", "West", "West Texas and the Permian Basin; heavy wind and solar."),
    Zone("LZ_AEN", "Austin Energy", "City of Austin municipal utility territory."),
    Zone("LZ_CPS", "CPS Energy", "City of San Antonio municipal utility territory."),
    Zone(
        "LZ_LCRA",
        "LCRA",
        "Lower Colorado River Authority wholesale customers; scattered across Central Texas.",
        on_map=False,
    ),
    Zone(
        "LZ_RAYBN",
        "Rayburn",
        "Rayburn Country Electric Cooperative members in Northeast Texas.",
        on_map=False,
    ),
]

ZONES_BY_CODE = {z.code: z for z in ZONES}
TRACKED_POINTS = [z.code for z in ZONES] + [REFERENCE_HUB]
