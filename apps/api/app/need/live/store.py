"""Reading NWS Alerts: which are Active for which Cells at a given `now`."""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Cell, NwsAlert, NwsAlertSnapshot
from app.need.config import nws_alerts as config


def active_alerts(db: Session, cells: list[Cell], now: datetime) -> dict[str, list[NwsAlert]]:
    """h3_index -> signals Active at `now` whose area contains the Cell's center:
    not superseded, and effective <= now < ends (or expires when NWS gives no end)."""
    result: dict[str, list[NwsAlert]] = {c.h3_index: [] for c in cells}
    if not cells:
        return result
    center = func.ST_SetSRID(func.ST_MakePoint(Cell.center_lng, Cell.center_lat), 4326)
    rows = db.execute(
        select(Cell.h3_index, NwsAlert)
        .join(NwsAlert, func.ST_Contains(NwsAlert.geometry, center))
        .where(
            Cell.h3_index.in_([c.h3_index for c in cells]),
            NwsAlert.superseded_at.is_(None),
            NwsAlert.effective_at <= now,
            NwsAlert.ends > now,
        )
        .order_by(NwsAlert.effective_at)
    )
    for h3_index, signal in rows:
        result[h3_index].append(signal)
    return result


def most_severe_category(signals: list[NwsAlert]) -> str | None:
    categories = {s.category for s in signals}
    return next((c for c in config.category_order if c in categories), None)


def alert_status(db: Session, now: datetime) -> tuple[datetime | None, bool]:
    """(time of the last successful Snapshot, stale?). Stale when none succeeded within
    `stale_after_minutes` of `now`."""
    fetched = db.scalar(
        select(func.max(NwsAlertSnapshot.fetched_at)).where(NwsAlertSnapshot.succeeded)
    )
    stale = fetched is None or now - fetched > timedelta(minutes=config.stale_after_minutes)
    return fetched, stale
