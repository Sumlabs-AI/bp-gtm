"""What a lead is worth to Base: its ERCOT load zone, the grid value of each battery size
there (from the zone backtest, app/grid), and the size we'd pitch.

Screening estimate only: energy-trading value of a battery on day-ahead plans
(app/grid/dispatch.py) in an average past year, after losses, wear and the backup reserve;
no retail margin, fees or ancillary services.
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
    {"LZ_HOUSTON": {"40": {"value": 891, "ceiling": 1650, "first_year": 2019,
    "last_year": 2025, "recent": 233, "low": 310, "low_year": 2025, "high": 1741,
    "high_year": 2023}, …}, …}.

    `value` is the realistic day-ahead-planner value of an average full calendar year (what
    a battery earns over a multi-year contract, not one quiet or spiky year) and `ceiling`
    the average perfect-hindsight one. Without full years loaded both fall back to the last
    12 months and first/last/low/high are None. `recent` is always the last 12 months."""
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT settlement_point, metrics, series FROM grid_zone_metrics"))
        values = {}
        for zone, metrics, series in rows:
            if any(metrics.get(f"battery_value_{k}") is None for k in LEAD_BATTERIES_KW):
                continue
            years = series.get("battery_years") or []
            values[zone] = {}
            for k in LEAD_BATTERIES_KW:
                size, ceil_key = str(k), f"ceiling_{k}"
                hist = years if all(ceil_key in y for y in years) else []
                if hist:
                    value = sum(y[size] for y in hist) / len(hist)
                    ceiling = sum(y[ceil_key] for y in hist) / len(hist)
                    low = min(hist, key=lambda y: y[size])
                    high = max(hist, key=lambda y: y[size])
                else:
                    value, ceiling = metrics[f"battery_value_{k}"], metrics[f"battery_ceiling_{k}"]
                values[zone][size] = {
                    "value": round(value),
                    "ceiling": round(ceiling),
                    "first_year": hist[0]["year"] if hist else None,
                    "last_year": hist[-1]["year"] if hist else None,
                    "recent": round(metrics[f"battery_value_{k}"]),
                    "low": round(low[size]) if hist else None,
                    "low_year": low["year"] if hist else None,
                    "high": round(high[size]) if hist else None,
                    "high_year": high["year"] if hist else None,
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
