"""Live grid for the Need Engine: the ERCOT Grid Condition (official, as ERCOT declares it)
and Grid Stress Signals (our thresholds on ERCOT data), derived at read time from stored
polls and grid_prices with an explicit `now`. Never merged, never scored here.
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.grid.config import scoring as grid_scoring
from app.grid.store import upsert_prices
from app.models import Cell, GridCondition, GridPrice
from app.need.config import grid_live as config
from app.need.live.ercot import parse_condition

ERCOT_TZ = ZoneInfo("America/Chicago")
NORMAL = "normal"  # ERCOT's own state value when nothing is declared
NO_ZONE = "No Load Zone for this Cell: price signals unavailable"


@dataclass
class StressSignal:
    """A Grid Stress Signal: our reading of ERCOT data, not an ERCOT declaration."""

    type: str  # low_reserves | tight_margin | rt_price_spike | dam_price_spike
    category: str  # "reliability" | "market"
    value: float
    threshold: float
    unit: str
    at: datetime | None
    message: str
    hours: int | None = None  # day-ahead spikes: hours at or above the threshold


def take_grid_poll(
    db: Session, fetch: Callable[[], tuple[dict, dict]], now: datetime
) -> GridCondition:
    """Poll the dashboards at `now`; a failure is logged and changes nothing. Caller commits."""
    try:
        row = GridCondition(fetched_at=now, succeeded=True, **parse_condition(*fetch()))
    except Exception as exc:
        row = GridCondition(fetched_at=now, succeeded=False, error=f"{type(exc).__name__}: {exc}")
    db.add(row)
    db.flush()
    return row


def refresh_prices(market: str, fetch: Callable[[str, int], pd.DataFrame]) -> int:
    """Upsert the latest MIS publications for RT or DA into grid_prices (idempotent).
    Writes in upsert_prices' own transaction, like the existing price loaders."""
    documents = config.rt_documents if market == "RT" else config.dam_documents
    return upsert_prices(fetch(market, documents))


def latest_condition(db: Session, now: datetime) -> GridCondition | None:
    return db.scalars(
        select(GridCondition)
        .where(GridCondition.succeeded, GridCondition.fetched_at <= now)
        .order_by(GridCondition.fetched_at.desc())
        .limit(1)
    ).first()


def is_stale(row: GridCondition | None, now: datetime) -> bool:
    return row is None or now - row.fetched_at > timedelta(minutes=config.condition_stale_minutes)


def is_official(row: GridCondition | None) -> bool:
    """True only when ERCOT declares something other than normal."""
    return row is not None and (row.state != NORMAL or (row.eea_level or 0) > 0)


def condition_summary(row: GridCondition | None, now: datetime) -> dict:
    """The ERCOT-wide condition as the API shows it (same for every Cell)."""
    return {
        "state": row.state if row else None,
        "title": row.title if row else None,
        "eeaLevel": row.eea_level if row else None,
        "official": is_official(row),
        "stale": is_stale(row, now),
    }


def _reliability(row: GridCondition | None, now: datetime) -> list[StressSignal]:
    if is_stale(row, now):  # an old reading is not a live signal
        return []
    signals = []
    if row.prc_mw is not None and row.prc_mw < config.prc_low_mw:
        signals.append(
            StressSignal(
                "low_reserves",
                "reliability",
                row.prc_mw,
                config.prc_low_mw,
                "MW",
                row.source_updated_at,
                f"Reserves (PRC) {row.prc_mw:,} MW, below our {config.prc_low_mw:,} MW",
            )
        )
    tight, at = row.margin_forecast_min_mw, row.margin_forecast_min_at
    if tight is not None and tight < config.margin_low_mw and (at is None or at > now):
        signals.append(
            StressSignal(
                "tight_margin",
                "reliability",
                tight,
                config.margin_low_mw,
                "MW",
                at,
                f"ERCOT forecasts only {tight:,} MW of spare capacity later today",
            )
        )
    return signals


def _latest_rt(db: Session, zones: set[str], now: datetime) -> dict[str, GridPrice]:
    latest = (
        select(GridPrice.settlement_point, func.max(GridPrice.interval_start).label("at"))
        .where(
            GridPrice.market == "RT",
            GridPrice.settlement_point.in_(zones),
            GridPrice.interval_start <= now,
        )
        .group_by(GridPrice.settlement_point)
        .subquery()
    )
    rows = db.scalars(
        select(GridPrice).join(
            latest,
            (GridPrice.settlement_point == latest.c.settlement_point)
            & (GridPrice.interval_start == latest.c.at)
            & (GridPrice.market == "RT"),
        )
    )
    return {p.settlement_point: p for p in rows}


def _dam_upcoming(db: Session, zones: set[str], now: datetime) -> dict[str, list[GridPrice]]:
    """Day-ahead hours still to come, through the end of tomorrow (ERCOT local), at or above
    the scarcity price: today's remaining hours before DAM publishes tomorrow's."""
    local_today = now.astimezone(ERCOT_TZ).date()
    end = datetime.combine(local_today + timedelta(days=2), datetime.min.time(), ERCOT_TZ)
    rows = db.scalars(
        select(GridPrice)
        .where(
            GridPrice.market == "DA",
            GridPrice.settlement_point.in_(zones),
            GridPrice.interval_start + timedelta(hours=1) > now,
            GridPrice.interval_start < end,
            GridPrice.price >= grid_scoring.scarcity_threshold,
        )
        .order_by(GridPrice.interval_start)
    )
    out: dict[str, list[GridPrice]] = {}
    for p in rows:
        out.setdefault(p.settlement_point, []).append(p)
    return out


def _market(zone: str, latest: GridPrice | None, spikes: list[GridPrice], fresh: bool) -> list:
    threshold = grid_scoring.scarcity_threshold
    signals = []
    if fresh and latest.price >= threshold:
        signals.append(
            StressSignal(
                "rt_price_spike",
                "market",
                latest.price,
                threshold,
                "$/MWh",
                latest.interval_start,
                f"Real-time price in {zone} ${latest.price:,.0f}/MWh",
            )
        )
    if spikes:
        peak = max(p.price for p in spikes)
        signals.append(
            StressSignal(
                "dam_price_spike",
                "market",
                peak,
                threshold,
                "$/MWh",
                spikes[0].interval_start,
                f"Day-ahead price in {zone} reaches ${peak:,.0f}/MWh "
                f"({len(spikes)} hours at or above ${threshold:,.0f})",
                hours=len(spikes),
            )
        )
    return signals


def grid_live(db: Session, cells: list[Cell], now: datetime) -> dict[str, dict]:
    """h3_index -> {condition, prices, stressSignals, notes} at `now` (a few queries in
    total, whatever the number of Cells)."""
    row = latest_condition(db, now)
    condition = {
        **condition_summary(row, now),
        "prcMw": row.prc_mw if row else None,
        "sourceUpdatedAt": row.source_updated_at if row else None,
        "fetchedAt": row.fetched_at if row else None,
    }
    reliability = _reliability(row, now)
    zones = {c.load_zone for c in cells if c.load_zone}
    rt = _latest_rt(db, zones, now) if zones else {}
    dam = _dam_upcoming(db, zones, now) if zones else {}
    price_stale_after = timedelta(minutes=config.price_stale_minutes)
    result = {}
    for cell in cells:
        zone = cell.load_zone
        latest = rt.get(zone) if zone else None
        fresh = latest is not None and now - latest.interval_start <= price_stale_after
        market = _market(zone, latest, dam.get(zone, []), fresh) if zone else []
        result[cell.h3_index] = {
            "condition": condition,
            "prices": {
                "loadZone": zone,
                "latestRt": {"price": latest.price, "intervalStart": latest.interval_start}
                if latest
                else None,
                "stale": not fresh,
            },
            "stressSignals": [asdict(s) for s in reliability + market],
            "notes": [] if zone else [NO_ZONE],
        }
    return result
