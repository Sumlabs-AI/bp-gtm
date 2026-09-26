"""Live grid for the Need Engine: the ERCOT Grid Condition (official, as ERCOT declares it)
and Grid Stress Signals (our thresholds on ERCOT data), derived at read time from stored
polls and grid_prices with an explicit `now`. Never merged, never scored here.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.grid.config import scoring as grid_scoring
from app.grid.store import upsert_prices
from app.models import Cell, GridCondition, GridPrice
from app.need.config import grid_live as config
from app.need.live.ercot import parse_condition

ERCOT_TZ = ZoneInfo("America/Chicago")
NO_ZONE = "No Load Zone for this Cell: price signals unavailable"


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


def refresh_prices(market: str, fetch: Callable[[str, int], object]) -> int:
    """Upsert the latest MIS publications for RT or DA into grid_prices (idempotent)."""
    documents = config.rt_documents if market == "RT" else config.dam_documents
    return upsert_prices(fetch(market, documents))


def _condition(db: Session, now: datetime) -> dict:
    last = db.scalars(
        select(GridCondition)
        .where(GridCondition.succeeded, GridCondition.fetched_at <= now)
        .order_by(GridCondition.fetched_at.desc())
        .limit(1)
    ).first()
    stale_after = timedelta(minutes=config.condition_stale_minutes)
    if last is None:
        return {
            "state": None,
            "title": None,
            "eeaLevel": None,
            "prcMw": None,
            "official": False,
            "sourceUpdatedAt": None,
            "fetchedAt": None,
            "stale": True,
            "_row": None,
        }
    return {
        "state": last.state,
        "title": last.title,
        "eeaLevel": last.eea_level,
        "prcMw": last.prc_mw,
        # Official only when ERCOT declares something other than normal.
        "official": last.state != config.normal_state or (last.eea_level or 0) > 0,
        "sourceUpdatedAt": last.source_updated_at,
        "fetchedAt": last.fetched_at,
        "stale": now - last.fetched_at > stale_after,
        "_row": last,
    }


def _reliability(row: GridCondition | None, now: datetime) -> list[dict]:
    if row is None:
        return []
    signals = []
    if row.prc_mw is not None and row.prc_mw < config.prc_low_mw:
        signals.append(
            {
                "type": "low_reserves",
                "category": "reliability",
                "value": row.prc_mw,
                "threshold": config.prc_low_mw,
                "unit": "MW",
                "at": row.source_updated_at,
                "message": f"Reserves (PRC) {row.prc_mw:,} MW, below our {config.prc_low_mw:,} MW",
            }
        )
    tight = row.margin_forecast_min_mw
    if (
        tight is not None
        and tight < config.margin_low_mw
        and (row.margin_forecast_min_at is None or row.margin_forecast_min_at > now)
    ):
        signals.append(
            {
                "type": "tight_margin",
                "category": "reliability",
                "value": tight,
                "threshold": config.margin_low_mw,
                "unit": "MW",
                "at": row.margin_forecast_min_at,
                "message": f"ERCOT forecasts only {tight:,} MW of spare capacity later today",
            }
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


def _dam_tomorrow(db: Session, zones: set[str], now: datetime) -> dict[str, list[GridPrice]]:
    local_today = now.astimezone(ERCOT_TZ).date()
    start = datetime.combine(local_today + timedelta(days=1), datetime.min.time(), ERCOT_TZ)
    rows = db.scalars(
        select(GridPrice)
        .where(
            GridPrice.market == "DA",
            GridPrice.settlement_point.in_(zones),
            GridPrice.interval_start >= start,
            GridPrice.interval_start < start + timedelta(days=1),
            GridPrice.price >= grid_scoring.scarcity_threshold,
        )
        .order_by(GridPrice.interval_start)
    )
    out: dict[str, list[GridPrice]] = {}
    for p in rows:
        out.setdefault(p.settlement_point, []).append(p)
    return out


def grid_live(db: Session, cells: list[Cell], now: datetime) -> dict[str, dict]:
    """h3_index -> {condition, prices, stressSignals, notes} at `now` (a few queries total,
    whatever the number of Cells)."""
    condition = _condition(db, now)
    reliability = _reliability(condition.pop("_row"), now)
    zones = {c.load_zone for c in cells if c.load_zone}
    rt = _latest_rt(db, zones, now) if zones else {}
    dam = _dam_tomorrow(db, zones, now) if zones else {}
    threshold = grid_scoring.scarcity_threshold
    price_stale_after = timedelta(minutes=config.price_stale_minutes)
    result = {}
    for cell in cells:
        zone = cell.load_zone
        latest = rt.get(zone) if zone else None
        fresh = latest is not None and now - latest.interval_start <= price_stale_after
        market = []
        if fresh and latest.price >= threshold:
            market.append(
                {
                    "type": "rt_price_spike",
                    "category": "market",
                    "value": latest.price,
                    "threshold": threshold,
                    "unit": "$/MWh",
                    "at": latest.interval_start,
                    "message": f"Real-time price in {zone} ${latest.price:,.0f}/MWh",
                }
            )
        spikes = dam.get(zone, []) if zone else []
        if spikes:
            peak = max(p.price for p in spikes)
            market.append(
                {
                    "type": "dam_price_spike",
                    "category": "market",
                    "value": peak,
                    "threshold": threshold,
                    "unit": "$/MWh",
                    "at": spikes[0].interval_start,
                    "message": f"Tomorrow's day-ahead price in {zone} reaches ${peak:,.0f}/MWh "
                    f"({len(spikes)} hours at or above ${threshold:,.0f})",
                }
            )
        result[cell.h3_index] = {
            "condition": condition,
            "prices": {
                "loadZone": zone,
                "latestRt": {"price": latest.price, "intervalStart": latest.interval_start}
                if latest
                else None,
                "stale": not fresh,
            },
            "stressSignals": reliability + market,
            "notes": [] if zone else [NO_ZONE],
        }
    return result
