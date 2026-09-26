"""Need Engine settings. Not secrets, so they live in code (like app/grid/config.py)."""

from pydantic import BaseModel

from app import geo


class NeedConfig(BaseModel):
    # Resolution Cells are seeded at. Changing it means re-seeding (cells keep their own).
    h3_resolution: int = geo.RESOLUTION
    # Safety cap for GET /need/cells; the map also hides Cells when zoomed out.
    viewport_max_cells: int = 20_000


need = NeedConfig()
