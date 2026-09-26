"""What a lead is worth to Base: its ERCOT load zone, the grid value of each battery size
there (from the zone backtest, app/grid), and the size we'd pitch.

Screening estimate only: energy-arbitrage value of a battery trading on day-ahead plans
(app/grid/dispatch.py), after losses, wear and the backup reserve; no retail margin, fees
or ancillary services.
"""

import geopandas as gpd
import pandas as pd
from sqlalchemy import text

from app.db import engine
from app.grid.config import LEAD_BATTERIES_KW
from app.grid.zones import ZONES_GEOJSON
from app.leads.config import TDSP_ZONES, LeadScoringConfig


def assign_zones(homes: pd.DataFrame) -> pd.Series:
    """Load zone per row from its lat/lon (point in zone polygon), else from its TDSP."""
    zones = gpd.read_file(ZONES_GEOJSON)[["code", "geometry"]]
    points = gpd.GeoDataFrame(
        index=homes.index, geometry=gpd.points_from_xy(homes["lon"], homes["lat"]), crs=4326
    )
    hits = gpd.sjoin(points[points.geometry.is_valid], zones, predicate="within")
    # Municipal territories (Austin Energy, CPS) sit inside larger zones: smallest wins.
    hits["area"] = zones.to_crs(3081).area.reindex(hits["index_right"]).to_numpy()
    by_point = hits.sort_values("area").groupby(level=0)["code"].first()
    return by_point.reindex(homes.index).fillna(homes["tdsp"].map(TDSP_ZONES))


def zone_battery_values() -> dict[str, dict[str, dict]]:
    """Per zone and battery size, from the latest grid compute:
    {"LZ_HOUSTON": {"25": {"value": 194, "ceiling": 363, "low": 120, "low_year": 2020,
    "high": 900, "high_year": 2023}, …}, …}. `value` is the realistic day-ahead-planner
    value over the last year, `ceiling` the perfect-hindsight one, low/high the worst and
    best full calendar years (None before the history is loaded)."""
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT settlement_point, metrics, series FROM grid_zone_metrics"))
        values = {}
        for zone, metrics, series in rows:
            if any(metrics.get(f"battery_value_{k}") is None for k in LEAD_BATTERIES_KW):
                continue
            years = series.get("battery_years") or []
            values[zone] = {}
            for k in LEAD_BATTERIES_KW:
                low = min(years, key=lambda y: y[str(k)], default=None)
                high = max(years, key=lambda y: y[str(k)], default=None)
                values[zone][str(k)] = {
                    "value": round(metrics[f"battery_value_{k}"]),
                    "ceiling": round(metrics[f"battery_ceiling_{k}"]),
                    "low": low and round(low[str(k)]),
                    "low_year": low and low["year"],
                    "high": high and round(high[str(k)]),
                    "high_year": high and high["year"],
                }
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
