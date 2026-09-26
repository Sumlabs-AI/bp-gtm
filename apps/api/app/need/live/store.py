"""Reading Live Weather Signals: which are Active for which Cells at a given `now`."""

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Cell, LiveWeatherSignal, LiveWeatherSnapshot
from app.need.config import live_weather as config


def active_signals(
    db: Session, cells: list[Cell], now: datetime
) -> dict[str, list[LiveWeatherSignal]]:
    """h3_index -> signals Active at `now` whose area contains the Cell's center:
    not superseded, and effective <= now < ends (or expires when NWS gives no end)."""
    result: dict[str, list[LiveWeatherSignal]] = {c.h3_index: [] for c in cells}
    if not cells:
        return result
    center = func.ST_SetSRID(func.ST_MakePoint(Cell.center_lng, Cell.center_lat), 4326)
    ends = func.coalesce(LiveWeatherSignal.ends_at, LiveWeatherSignal.expires_at)
    rows = db.execute(
        select(Cell.h3_index, LiveWeatherSignal)
        .join(LiveWeatherSignal, func.ST_Contains(LiveWeatherSignal.geometry, center))
        .where(
            Cell.h3_index.in_([c.h3_index for c in cells]),
            LiveWeatherSignal.superseded_at.is_(None),
            LiveWeatherSignal.effective_at <= now,
            ends > now,
        )
        .order_by(LiveWeatherSignal.effective_at)
    )
    by_cell = defaultdict(list)
    for h3_index, signal in rows:
        by_cell[h3_index].append(signal)
    result.update(by_cell)
    return result


def live_status(db: Session, now: datetime) -> tuple[datetime | None, bool]:
    """(time of the last successful Snapshot, stale?). Stale when none succeeded within
    `stale_after_minutes` of `now`."""
    fetched = db.scalar(
        select(func.max(LiveWeatherSnapshot.fetched_at)).where(LiveWeatherSnapshot.succeeded)
    )
    stale = fetched is None or now - fetched > timedelta(minutes=config.stale_after_minutes)
    return fetched, stale
