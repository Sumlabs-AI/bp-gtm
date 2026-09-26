"""Public ERCOT dashboards (no login) for the live Grid Need inputs.

`daily-prc.json` carries the grid condition ERCOT declares (the ERCOT Grid Condition) and
PRC, reserves available in real time. `supply-demand.json` carries 5-minute capacity and
demand today, plus ERCOT's forecast to midnight.
"""

from datetime import UTC, datetime

import httpx

DASHBOARD = "https://www.ercot.com/api/1/services/read/dashboards/{}.json"
_UA = {"User-Agent": "base-power-gtm need engine"}


def _time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S%z").astimezone(UTC)


def parse_condition(prc: dict, supply_demand: dict) -> dict:
    """One grid_conditions row (without fetched_at) from the two dashboards."""
    current = prc["current_condition"]
    rows = supply_demand["data"]
    actual = [r for r in rows if not r["forecast"]]
    forecast = [r for r in rows if r["forecast"]]
    tightest = min(forecast, key=lambda r: r["capacity"] - r["demand"]) if forecast else None
    return {
        "source_updated_at": _time(prc["lastUpdated"]),
        "state": current["state"],
        "title": current["title"],
        "eea_level": int(current["eea_level"]),
        "prc_mw": int(str(current["prc_value"]).replace(",", "")),
        "capacity_mw": actual[-1]["capacity"] if actual else None,
        "demand_mw": actual[-1]["demand"] if actual else None,
        "margin_forecast_min_mw": tightest["capacity"] - tightest["demand"] if tightest else None,
        "margin_forecast_min_at": _time(tightest["timestamp"]) if tightest else None,
    }


def fetch_dashboards() -> tuple[dict, dict]:
    with httpx.Client(headers=_UA, timeout=30) as http:
        prc = http.get(DASHBOARD.format("daily-prc")).raise_for_status().json()
        sd = http.get(DASHBOARD.format("supply-demand")).raise_for_status().json()
    return prc, sd
