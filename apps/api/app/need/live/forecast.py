"""Forecast Signals: our deterministic reading of NWS gridded forecasts and SPC outlooks.

Not NWS Alerts: nothing here is issued by NWS as a warning. A signal is one continuous
period in which a forecast value crosses one of our fixed thresholds (config), or the
highest SPC risk area covering a point.
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Literal

from shapely.geometry import Point, shape

from app.need.config import ForecastCondition
from app.need.config import forecast as config

_DURATION = re.compile(r"P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?$")
COMPARISON = {"ge": ">=", "le": "<="}
# NWS units -> ours.
_CONVERT = {
    "mph": lambda kmh: kmh / 1.609344,
    "°F": lambda c: c * 9 / 5 + 32,
    "in": lambda mm: mm / 25.4,
}


def _interval(valid_time: str) -> tuple[datetime, datetime]:
    """NWS "start/ISO-8601 duration" -> (start, end)."""
    start, duration = valid_time.split("/")
    match = _DURATION.match(duration)
    if not match or duration == "P":
        raise ValueError(f"unsupported NWS duration {duration!r}")
    weeks, days, hours, minutes = (int(x or 0) for x in match.groups())
    begin = datetime.fromisoformat(start).astimezone(UTC)
    return begin, begin + timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes)


def update_time(gridpoint: dict) -> datetime:
    """When NWS issued this forecast (not when we fetched it)."""
    return datetime.fromisoformat(gridpoint["properties"]["updateTime"]).astimezone(UTC)


def _steps(layer: dict, c: ForecastCondition) -> list[tuple[datetime, datetime, float]]:
    """(start, end, value in our unit) per clock hour (cut at the interval's own edges, so
    intervals off the hour never overlap), or per interval for accumulations."""
    if layer.get("values") and layer.get("uom") != c.nws_uom:
        raise ValueError(f"unexpected unit {layer.get('uom')!r} for {c.variable}")
    steps = []
    for v in layer.get("values", []):
        if v["value"] is None:
            continue
        start, end = _interval(v["validTime"])
        value = _CONVERT[c.unit](v["value"])
        if c.per_interval:
            steps.append((start, end, value))
            continue
        at = start
        while at < end:
            next_hour = at.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            steps.append((at, min(next_hour, end), value))
            at = min(next_hour, end)
    return sorted(steps)


def _crosses(value: float, threshold: float, direction: Literal["ge", "le"]) -> bool:
    return value >= threshold if direction == "ge" else value <= threshold


def _periods(
    steps: list[tuple[datetime, datetime, float]], c: ForecastCondition, now: datetime
) -> list[dict]:
    """Contiguous threshold-crossing steps merged into periods. The peak (and so the level)
    only counts steps not over yet: a period under way reports what is still to come."""
    periods: list[dict] = []
    worst = max if c.direction == "ge" else min
    for start, end, value in steps:
        if not _crosses(value, c.elevated, c.direction):
            continue
        last = periods[-1] if periods else None
        if last and last["end_at"] == start:  # contiguous: extend the period
            last["end_at"] = end
        else:
            last = {"start_at": start, "end_at": end, "peak": None}
            periods.append(last)
        if end > now:
            last["peak"] = value if last["peak"] is None else worst(last["peak"], value)
    return [p for p in periods if p["peak"] is not None]


def grid_signals(gridpoint: dict, now: datetime) -> list[dict]:
    """Threshold-crossing periods in one NWS gridpoint forecast that are not over yet and
    start within the storage horizon (a period in progress keeps its real start). Which of
    them are Active (start within 48 h) is decided at read time."""
    props = gridpoint["properties"]
    updated = update_time(gridpoint)
    horizon_end = now + timedelta(hours=config.storage_horizon_hours)
    signals = []
    for condition, c in config.conditions.items():
        for p in _periods(_steps(props.get(c.variable) or {}, c), c, now):
            if p["end_at"] <= now or p["start_at"] >= horizon_end:
                continue
            high = _crosses(p["peak"], c.high, c.direction)
            signals.append(
                {
                    "source": "nws_grid",
                    "condition": condition,
                    "level": "high" if high else "elevated",
                    "start_at": p["start_at"],
                    "end_at": p["end_at"],
                    "peak_value": round(p["peak"], 2),
                    "unit": c.unit,
                    "threshold": c.elevated,
                    "label": None,
                    "source_updated_at": updated,
                }
            )
    return signals


def spc_signals(outlooks: list[dict], points: dict[str, tuple[float, float]]) -> list[dict]:
    """One severe-storm signal per point per outlook day: the highest SPC category (Slight
    and above) whose area contains the point. `points`: res-6 h3 -> (lat, lng)."""
    signals = []
    for outlook in outlooks:
        areas = [
            (f["properties"], shape(f["geometry"]))
            for f in outlook["features"]
            if f["properties"].get("LABEL") in config.spc_levels and f.get("geometry")
        ]
        for h3_index, (lat, lng) in points.items():
            here = [props for props, area in areas if area.contains(Point(lng, lat))]
            if not here:
                continue
            rank = list(config.spc_levels)
            top = max(here, key=lambda p: rank.index(p["LABEL"]))
            signals.append(
                {
                    "h3_index": h3_index,
                    "source": "spc_outlook",
                    "condition": "severe_storm",
                    "level": config.spc_levels[top["LABEL"]],
                    "start_at": datetime.fromisoformat(top["VALID_ISO"]).astimezone(UTC),
                    "end_at": datetime.fromisoformat(top["EXPIRE_ISO"]).astimezone(UTC),
                    "peak_value": None,
                    "unit": None,
                    "threshold": None,
                    "label": top["LABEL"],
                    "source_updated_at": datetime.fromisoformat(top["ISSUE_ISO"]).astimezone(UTC),
                }
            )
    return signals
