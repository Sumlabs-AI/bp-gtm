"""Forecast Signals in Postgres: hourly runs, per-point replacement, read-time Active.

Each res-6 forecast point is replaced only when its own fetch and parse succeed; the SPC
outlook signals only when the SPC fetch succeeds. Nothing is deleted: replaced signals keep
their row with `replaced_at` (history for measuring overlaps in M4B-3).
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from app import geo
from app.models import Cell, ForecastPoint, ForecastRun, ForecastSignal
from app.need.config import forecast as config
from app.need.live.forecast import grid_signals, spc_signals, update_time


def _replace(
    db: Session, run: ForecastRun, points: list[str], source: str, rows: list[dict], now: datetime
) -> None:
    db.execute(
        update(ForecastSignal)
        .where(
            ForecastSignal.h3_index.in_(points),
            ForecastSignal.source == source,
            ForecastSignal.replaced_at.is_(None),
        )
        .values(replaced_at=now)
    )
    if rows:
        db.execute(
            insert(ForecastSignal), [{**r, "run_id": run.id, "fetched_at": now} for r in rows]
        )


def take_forecast_run(
    db: Session,
    fetch_grid: Callable[[ForecastPoint], dict],
    fetch_spc: Callable[[], list[dict]],
    now: datetime,
    lookup: Callable[[float, float], tuple[str, int, int]] | None = None,
) -> ForecastRun:
    """Refresh every forecast point and the SPC outlooks at `now`; with `lookup`, first add
    points for new Cells. Every attempt is logged, per-point errors included. A point whose
    NWS forecast hasn't changed (same updateTime) is only marked checked. The caller commits.
    """
    run = ForecastRun(started_at=now, points_ok=0, points_failed=0, spc_ok=False)
    run.point_errors = {}
    db.add(run)
    db.flush()
    if lookup is not None:
        run.point_errors.update(_sync_points(db, lookup))
    points = db.scalars(select(ForecastPoint).order_by(ForecastPoint.h3_index)).all()
    for point in points:
        try:
            gridpoint = fetch_grid(point)
            updated = update_time(gridpoint)
            if point.last_success_at is None or updated != point.source_updated_at:
                rows = [{**s, "h3_index": point.h3_index} for s in grid_signals(gridpoint, now)]
                with db.begin_nested():
                    _replace(db, run, [point.h3_index], "nws_grid", rows, now)
            point.last_success_at, point.source_updated_at, point.last_error = now, updated, None
            run.points_ok += 1
        except Exception as exc:  # this point keeps its previous signals
            point.last_error = run.point_errors[point.h3_index] = f"{type(exc).__name__}: {exc}"
            run.points_failed += 1
    try:
        centers = {p.h3_index: (p.lat, p.lng) for p in points}
        rows = spc_signals(fetch_spc(), centers)
        with db.begin_nested():
            _replace(db, run, list(centers), "spc_outlook", rows, now)
        run.spc_ok = True
    except Exception as exc:  # every point keeps its previous SPC signals
        run.spc_error = f"{type(exc).__name__}: {exc}"
    run.finished_at = datetime.now(UTC)  # wall clock: how long the run really took
    db.flush()
    return run


def active_forecast(
    db: Session, cells: list[Cell], now: datetime
) -> dict[str, list[ForecastSignal]]:
    """h3_index (res 8) -> Forecast Signals Active at `now` for its res-6 point: not
    replaced, not over, and starting within the horizon."""
    parents = {c.h3_index: geo.cell_to_parent(c.h3_index, config.resolution) for c in cells}
    rows = db.scalars(
        select(ForecastSignal)
        .where(
            ForecastSignal.h3_index.in_(set(parents.values())),
            ForecastSignal.replaced_at.is_(None),
            ForecastSignal.end_at > now,
            ForecastSignal.start_at < now + timedelta(hours=config.horizon_hours),
        )
        .order_by(ForecastSignal.start_at)
    ).all()
    by_point: dict[str, list[ForecastSignal]] = {}
    for s in rows:
        by_point.setdefault(s.h3_index, []).append(s)
    return {h: by_point.get(parent, []) for h, parent in parents.items()}


def forecast_status(db: Session, points: list[str], now: datetime) -> dict:
    """Freshness: per res-6 point for the NWS grid, and once for SPC. Stale when the last
    success is older than `stale_after_hours`."""
    stale_after = timedelta(hours=config.stale_after_hours)
    grid = {}
    for p in db.scalars(select(ForecastPoint).where(ForecastPoint.h3_index.in_(points))):
        grid[p.h3_index] = {
            "fetched_at": p.last_success_at,
            "source_updated_at": p.source_updated_at,
            "stale": p.last_success_at is None or now - p.last_success_at > stale_after,
        }
    spc_at = db.scalar(select(func.max(ForecastRun.started_at)).where(ForecastRun.spc_ok))
    return {
        "grid": grid,
        "spc": {"fetched_at": spc_at, "stale": spc_at is None or now - spc_at > stale_after},
    }


def most_severe_level(signals: list[ForecastSignal]) -> str | None:
    levels = {s.level for s in signals}
    return next((level for level in config.level_order if level in levels), None)


def _sync_points(db: Session, lookup: Callable[[float, float], tuple[str, int, int]]) -> dict:
    """Add a forecast point for every res-6 parent of a product Cell that lacks one, looking
    its NWS grid cell up once. A failed lookup skips that point (retried next run) and is
    returned as {h3: error}; it never stops the run."""
    known = set(db.scalars(select(ForecastPoint.h3_index)))
    parents = {geo.cell_to_parent(h, config.resolution) for h in db.scalars(select(Cell.h3_index))}
    errors = {}
    for h6 in sorted(parents - known):
        lat, lng = geo.cell_to_center(h6)
        try:
            office, x, y = lookup(lat, lng)
        except Exception as exc:
            errors[h6] = f"grid lookup {type(exc).__name__}: {exc}"
            continue
        db.add(ForecastPoint(h3_index=h6, lat=lat, lng=lng, office=office, grid_x=x, grid_y=y))
    db.flush()
    return errors
