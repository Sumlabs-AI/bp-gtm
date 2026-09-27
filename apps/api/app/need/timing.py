"""Timing multiplier: when to knock in a Cell, from the NWS Alerts that covered it.

1.0 normally; `pre_event` while an alert is in effect or due within `pre_event_hours`; `peak`
for the weeks after a warning ends, fading back to 1.0 (longer after a major event). The
strongest applicable phase wins: one storm brings several alerts and must not count twice.

Timing multiplies the Opportunity Score (app/need/opportunity.py). Settings: app/need/config.py
(timing).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Float, String, column, func, select, values
from sqlalchemy.orm import Session

from app.models import Cell, NwsAlert
from app.need.config import nws_alerts as alert_config
from app.need.config import timing as config

METHOD = (
    f"x{config.pre_event:g} while a weather alert is in effect or due within "
    f"{config.pre_event_hours} h; x{config.peak:g} for {config.peak_days} days after a warning "
    f"ends, fading to x1 at {config.fade_days} days ({config.major_peak_days} and "
    f"{config.major_fade_days} days after a major event: ice/winter storm, extreme cold, "
    "hurricane). The strongest phase wins."
)
LIMITATIONS = [
    "Window shape from backup permits after two winter storms in Austin/San Antonio; "
    "no Houston permits to check it against.",
    "Only NWS Alerts seen by our poller: history starts when polling started.",
    "An alert is an event that may have spared this Cell; outage data would confirm it.",
]


@dataclass(frozen=True)
class AlertEvent:
    """What Timing needs from an NWS Alert."""

    event: str
    starts: datetime
    ends: datetime


@dataclass(frozen=True)
class Timing:
    multiplier: float
    phase: str  # "none" | "pre_event" | "peak" | "fading"
    event: str | None = None
    ends: datetime | None = None
    days_since: float | None = None
    major: bool = False


NONE = Timing(1.0, "none")


def _post_event(e: AlertEvent, now: datetime) -> Timing:
    major = e.event in config.major_events
    if not major and e.event not in config.events:
        return NONE
    days = (now - e.ends) / timedelta(days=1)
    peak_days = config.major_peak_days if major else config.peak_days
    fade_days = config.major_fade_days if major else config.fade_days
    if days <= peak_days:
        return Timing(config.peak, "peak", e.event, e.ends, round(days, 1), major)
    if days < fade_days:
        left = (fade_days - days) / (fade_days - peak_days)
        multiplier = round(1 + (config.peak - 1) * left, 3)
        return Timing(multiplier, "fading", e.event, e.ends, round(days, 1), major)
    return NONE


def timing_for(events: list[AlertEvent], now: datetime) -> Timing:
    """The strongest phase over every alert that covered one Cell."""
    best = NONE
    for e in events:
        if e.starts > now + timedelta(hours=config.pre_event_hours):
            continue
        if e.ends > now:
            t = Timing(
                config.pre_event, "pre_event", e.event, e.ends, None, e.event in config.major_events
            )
        else:
            t = _post_event(e, now)
        if t.multiplier > best.multiplier:
            best = t
    return best


def lookback() -> timedelta:
    return timedelta(days=max(config.fade_days, config.major_fade_days))


def timing_by_cell(
    db: Session, now: datetime, cells: list[Cell] | None = None
) -> dict[str, Timing]:
    """h3_index -> Timing, for the given Cells (or every Cell an alert touched; Cells with no
    alert are left out and count as 1.0).

    An alert that NWS cancelled or replaced ends when we saw it go (its `superseded_at`)."""
    ends = func.least(NwsAlert.ends, func.coalesce(NwsAlert.superseded_at, NwsAlert.ends))
    center = func.ST_SetSRID(func.ST_MakePoint(Cell.center_lng, Cell.center_lat), 4326)
    query = (
        select(Cell.h3_index, NwsAlert.event, NwsAlert.effective_at, ends)
        .join(NwsAlert, func.ST_Contains(NwsAlert.geometry, center))
        .where(
            NwsAlert.event.in_(list(alert_config.categories)),
            NwsAlert.effective_at <= now + timedelta(hours=config.pre_event_hours),
            ends >= now - lookback(),
            NwsAlert.effective_at <= ends,
        )
    )
    if cells is not None:
        query = query.where(Cell.h3_index.in_([c.h3_index for c in cells]))
    events: dict[str, list[AlertEvent]] = {}
    for h3_index, event, starts, end in db.execute(query):
        events.setdefault(h3_index, []).append(AlertEvent(event, starts, end))
    result = {h3: timing_for(e, now) for h3, e in events.items()}
    if cells is not None:
        for c in cells:
            result.setdefault(c.h3_index, NONE)
    return result


def timing_sql(db: Session, now: datetime):
    """(h3_index, multiplier) for every Cell with Timing > 1, as a subquery to outer-join
    (a missing row means 1.0). None when no Cell has any."""
    rows = [(h3, t.multiplier) for h3, t in timing_by_cell(db, now).items() if t.multiplier > 1]
    if not rows:
        return None
    return (
        values(column("h3_index", String), column("multiplier", Float), name="timing")
        .data(rows)
        .alias("timing")
    )
