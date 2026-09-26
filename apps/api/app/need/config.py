"""Need Engine settings. Not secrets, so they live in code (like app/grid/config.py)."""

from pydantic import BaseModel

from app import geo
from app.need.outage.eaglei import ExposureConfig
from app.need.outage.events import EventRules


class NeedConfig(BaseModel):
    # Resolution Cells are seeded at. Changing it means re-seeding (cells keep their own).
    h3_resolution: int = geo.RESOLUTION
    # Safety cap for GET /need/cells; the map also hides Cells when zoomed out.
    viewport_max_cells: int = 20_000


need = NeedConfig()

# Baseline Outage Need (re-run `python -m app.need outage compute` after changing them).
outage_events = EventRules()
outage_exposure = ExposureConfig()

# Cell -> EIA utility id from data we already have (no licensed territory layer):
# Austin Energy's territory is LZ_AEN; Harris County is CenterPoint. Anything else: unknown.
UTILITY_BY_LOAD_ZONE = {"LZ_AEN": 1015}  # Austin Energy
UTILITY_BY_COUNTY = {"48201": 8901}  # CenterPoint Energy (Harris)
