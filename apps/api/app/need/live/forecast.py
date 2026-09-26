"""Forecast Signals: our deterministic reading of NWS gridded forecasts and SPC outlooks.

Not NWS Alerts: nothing here is issued by NWS as a warning. A signal is one continuous
period in which a forecast value crosses one of our fixed thresholds (config), or the
highest SPC risk area covering a point.
"""

import re
from datetime import UTC, datetime, timedelta

from shapely.geometry import Point, shape

from app.need.config import ForecastCondition
from app.need.config import forecast as config

_DURATION = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?$")
# NWS units -> ours.
_CONVERT = {
    "mph": lambda kmh: kmh / 1.609344,
    "°F": lambda c: c * 9 / 5 + 32,
    "in": lambda mm: mm / 25.4,
}


def _interval(valid_time: str) -> tuple[datetime, datetime]:
    """NWS "start/ISO-8601 duration" -> (start, end)."""
    start, duration = valid_time.split("/")
    days, hours, minutes = (int(x or 0) for x in _DURATION.match(duration).groups())
    begin = datetime.fromisoformat(start).astimezone(UTC)
    return begin, begin + timedelta(days=days, hours=hours, minutes=minutes)


def _steps(values: list[dict], c: ForecastCondition) -> list[tuple[datetime, datetime, float]]:
    """(start, end, value in our unit) per hour, or per interval for accumulations."""
    steps = []
    for v in values:
        if v["value"] is None:
            continue
        start, end = _interval(v["validTime"])
        value = _CONVERT[c.unit](v["value"])
        if c.per_interval:
            steps.append((start, end, value))
            continue
        hour = start
        while hour < end:
            steps.append((hour, hour + timedelta(hours=1), value))
            hour += timedelta(hours=1)
    return sorted(steps)


def _crosses(value: float, threshold: float, direction: str) -> bool:
    return value >= threshold if direction == "ge" else value <= threshold


def _periods(steps: list[tuple[datetime, datetime, float]], c: ForecastCondition) -> list[dict]:
    periods: list[dict] = []
    for start, end, value in steps:
        if not _crosses(value, c.elevated, c.direction):
            continue
        last = periods[-1] if periods else None
        if last and last["end_at"] == start:  # contiguous: extend the period
            last["end_at"] = end
            worse = value > last["peak"] if c.direction == "ge" else value < last["peak"]
            last["peak"] = value if worse else last["peak"]
        else:
            periods.append({"start_at": start, "end_at": end, "peak": value})
    return periods


def grid_signals(gridpoint: dict, now: datetime) -> list[dict]:
    """Threshold-crossing periods in one NWS gridpoint forecast that are not over yet and
    start within the horizon (a period in progress keeps its real start)."""
    props = gridpoint["properties"]
    updated = datetime.fromisoformat(props["updateTime"]).astimezone(UTC)
    horizon_end = now + timedelta(hours=config.horizon_hours)
    signals = []
    for condition, c in config.conditions.items():
        values = (props.get(c.variable) or {}).get("values", [])
        for p in _periods(_steps(values, c), c):
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
            top = max(here, key=lambda p: config.spc_rank.index(p["LABEL"]))
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
