"""Markets: named areas whose Cells we seed. Config only; Cells don't record their Market.

To add a Texas county: add it here, run scripts/download_counties.py, commit the GeoJSON,
then `python -m app.need seed --market <name>`.
"""

import json
from dataclasses import dataclass
from pathlib import Path

COUNTIES_DIR = Path(__file__).resolve().parents[1] / "geo/counties"


@dataclass(frozen=True)
class Market:
    name: str
    label: str
    geoid: str  # Census county GEOID: state FIPS + county FIPS

    @property
    def path(self) -> Path:
        return COUNTIES_DIR / f"tx-{self.name}.geojson"

    def geometry(self) -> dict:
        """The county (Multi)Polygon from the committed file (no network)."""
        return json.loads(self.path.read_text())["features"][0]["geometry"]


MARKETS = (
    Market("harris", "Harris County (Houston)", "48201"),
    Market("travis", "Travis County (Austin)", "48453"),
)
MARKETS_BY_NAME = {m.name: m for m in MARKETS}
