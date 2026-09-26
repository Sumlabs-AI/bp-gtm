"""What a lead is worth to Base: its ERCOT load zone, the grid value of each battery size
there (from the zone backtest, app/grid), and the size we'd pitch.

Screening estimate only: energy-trading value of a battery on day-ahead plans
(app/grid/dispatch.py) in an average past year, after losses, wear and the backup reserve;
no retail margin, fees or ancillary services.
"""

import pandas as pd
from sqlalchemy import text

from app.db import engine
from app.grid.metrics import battery_values
from app.grid.zones import zone_for_points
from app.leads.config import TDSP_ZONES, LeadScoringConfig


def assign_zones(homes: pd.DataFrame) -> pd.Series:
    """Load zone per row from its lat/lon (point in zone polygon), else from its TDSP."""
    return zone_for_points(homes["lat"], homes["lon"]).fillna(homes["tdsp"].map(TDSP_ZONES))


def zone_battery_values() -> dict[str, dict[str, dict]]:
    """Per zone, `battery_values` (app/grid/metrics.py) from the latest grid compute."""
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT settlement_point, metrics, series FROM grid_zone_metrics"))
        values = {}
        for zone, metrics, series in rows:
            sizes = battery_values(metrics, series)
            if sizes is not None:
                values[zone] = sizes
        return values


def recommend_battery(
    heated_sqft: float | None, has_pool: bool, cfg: LeadScoringConfig
) -> tuple[int, str]:
    sizes = [kwh for _, kwh in cfg.battery_sizing]
    if heated_sqft is None or pd.isna(heated_sqft):
        index, home = 0, "Home of unknown size"
    else:
        index = next(i for i, (limit, _) in enumerate(cfg.battery_sizing) if heated_sqft < limit)
        home = f"{heated_sqft:,.0f} sqft home"
    if has_pool:
        index = min(index + 1, len(sizes) - 1)
    return sizes[index], f"{home}{' with a pool' if has_pool else ''} → {sizes[index]} kWh"
