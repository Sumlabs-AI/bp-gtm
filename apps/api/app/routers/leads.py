import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import false, func, select
from sqlalchemy.orm import Session

from app import geo
from app.db import SessionLocal, get_db
from app.leads.address import split_mail_address
from app.leads.config import scoring
from app.leads.pipeline import SOURCES
from app.leads.scoring import DRIVERS
from app.models import CellBaselineNeed, Lead, Property, SourceRun
from app.need import for_leads
from app.need.config import NEED_BANDS
from app.routers.grid import BatteryValue

router = APIRouter(tags=["leads"])

DB = Annotated[Session, Depends(get_db)]
Status = Literal["new", "reviewed", "qualified", "excluded"]
Sort = Literal["need", "priority", "value", "consumption", "triggered_at"]
PERCENTILE_DRIVERS = {"home_size", "home_value"}
SIGNAL_TYPES = ("solar", "ev_charger", "new_home", "new_owner", "new_meter", "pool")


class CellBlock(BaseModel):
    """What a lead's H3 Cell says about it, read from the Need Engine at request time."""

    baseline_need: float | None
    propensity_score: float | None
    active_alerts: int
    forecast_level: str | None  # "elevated" | "high" | None
    grid_stress_signals: int


class LeadItem(BaseModel):
    id: int
    h3_index: str | None  # the Cell containing the home (the master key to the Need Engine)
    cell: CellBlock | None  # None when the home is outside every seeded Cell
    address: str | None
    city: str | None
    zip: str | None
    county: str
    score: float
    reasons: str
    signals: list[str]
    triggered_at: datetime | None
    trigger: str | None
    status: str
    load_zone: str | None
    battery_values: dict[str, BatteryValue] | None  # keyed by battery kWh
    recommended_kwh: int | None
    sizing_reason: str | None
    value: float | None  # $/yr for the recommended battery
    expected_value: float | None  # score/100 × value (Expected Value); a secondary sort
    annual_kwh: float | None  # estimated electricity use (median), see Consumption


class Consumption(BaseModel):
    """Property-based estimate of the home's electricity use; not metered data."""

    annual_kwh: float  # median estimate, kWh per year
    low_kwh: float  # P10–P90 range
    high_kwh: float
    monthly_kwh: list[float]  # Jan–Dec of a typical year, sums to annual_kwh
    peak_summer_kw: float  # the home's own highest daily demand, not diversified
    peak_winter_kw: float
    electric_heat_prob: float  # 0–1


class LeadListSummary(BaseModel):
    """The filtered set as a whole, for the bar above the list."""

    leads: int
    avg_baseline_need: float | None
    alert: int  # leads in a Cell under an active NWS Alert
    forecast: int  # ... with a Forecast Signal in the next 48 h
    grid_stress: int  # ... with a Grid Stress Signal
    grid_state: str | None  # the ERCOT Grid Condition (None when unknown or stale)


class LeadPage(BaseModel):
    total: int
    items: list[LeadItem]
    summary: LeadListSummary


class DriverOut(BaseModel):
    key: str
    label: str
    kind: Literal["percentile", "flag"]
    weight: float
    score: float
    value: float | bool | None


class Evidence(BaseModel):
    type: str
    date: str | None
    source: str
    detail: str


class LeadDetail(LeadItem):
    drivers: list[DriverOut]
    evidence: list[Evidence]
    account: str
    market_value: float | None
    heated_sqft: float | None
    year_built: int | None
    bedrooms: int | None
    full_baths: int | None
    half_baths: int | None
    stories: float | None
    consumption: Consumption | None
    first_seen_at: datetime
    scored_at: datetime
    lat: float | None
    lon: float | None


class LeadSummary(BaseModel):
    properties: int
    leads: int
    new_this_week: int
    by_signal: dict[str, int]
    by_zone: dict[str, int]  # load zone -> leads (all statuses); zones without leads omitted
    last_scored_at: datetime | None


class SourceStatus(BaseModel):
    source_id: str
    status: str | None
    started_at: datetime | None
    finished_at: datetime | None
    rows: int | None
    inserted: int | None
    updated: int | None
    error: str | None
    last_success_at: datetime | None


class StatusUpdate(BaseModel):
    status: Status


def _window() -> datetime:
    return datetime.now(UTC) - timedelta(days=scoring.new_window_days)


def _has_signal(kind: str):
    return Lead.signals.contains([{"type": kind}])


def _now() -> datetime:
    return datetime.now(UTC)


def _item(lead: Lead, prop: Property, cell: dict | None = None) -> dict:
    return {
        "id": prop.id,
        "h3_index": prop.h3_index,
        "cell": cell,
        "address": prop.situs_address,
        "city": prop.situs_city,
        "zip": prop.situs_zip,
        "county": prop.county,
        "score": lead.score,
        "reasons": lead.reasons,
        "signals": sorted({s["type"] for s in lead.signals}),
        "triggered_at": lead.triggered_at,
        "trigger": lead.trigger,
        "status": lead.status,
        "load_zone": lead.load_zone,
        "battery_values": lead.battery_values,
        "recommended_kwh": lead.recommended_kwh,
        "sizing_reason": lead.sizing_reason,
        "value": lead.value,
        "expected_value": lead.expected_value,
        "annual_kwh": lead.annual_kwh,
    }


@router.get("/leads/summary", response_model=LeadSummary)
def lead_summary(db: DB):
    return {
        "properties": db.scalar(select(func.count()).select_from(Property)),
        "leads": db.scalar(select(func.count()).select_from(Lead)),
        "new_this_week": db.scalar(
            select(func.count()).select_from(Lead).where(Lead.triggered_at >= _window())
        ),
        "by_signal": {
            k: db.scalar(select(func.count()).select_from(Lead).where(_has_signal(k)))
            for k in SIGNAL_TYPES
        },
        "by_zone": dict(
            db.execute(
                select(Lead.load_zone, func.count())
                .where(Lead.load_zone.is_not(None))
                .group_by(Lead.load_zone)
            ).all()
        ),
        "last_scored_at": db.scalar(select(func.max(Lead.scored_at))),
    }


class LeadFilters(BaseModel):
    """Filters shared by the list and the map."""

    min_score: float = 0
    signals: list[str] = []
    new_only: bool = False
    zip: str | None = None
    status: Status | None = None
    zone: str | None = None  # ERCOT load zone code, e.g. LZ_HOUSTON
    # Cell filters (the map as a filter): every one narrows to Cells and drops homes that
    # fall outside every seeded Cell.
    cells: list[str] = []  # H3 res-8 ids (clicked Cells)
    need_band: list[str] = []  # Baseline Need bands (the legend), see NEED_BANDS
    alert: bool = False  # only Cells under an active NWS Alert
    forecast: bool = False  # only Cells with a Forecast Signal in the next 48 h
    grid_stress: bool = False  # only Cells with a Grid Stress Signal
    bbox: str | None = None  # west,south,east,north: the map viewport

    def cell_set(self, db: Session, live: for_leads.LiveCells) -> set[str] | None:
        """The Cells the Cell filters allow, or None when no Cell filter is active."""
        allowed: set[str] | None = None

        def narrow(cells: set[str]) -> None:
            nonlocal allowed
            allowed = cells if allowed is None else allowed & cells

        if self.cells:
            narrow(set(self.cells))
        if self.need_band:
            narrow(for_leads.cells_in_bands(db, self.need_band))
        if self.alert:
            narrow(live.alert)
        if self.forecast:
            narrow(live.forecast)
        if self.grid_stress:
            narrow(live.grid_stress)
        return allowed

    def bounds(self) -> tuple[float, float, float, float] | None:
        if not self.bbox:
            return None
        try:
            west, south, east, north = (float(v) for v in self.bbox.split(","))
        except ValueError:
            raise HTTPException(422, "bbox must be west,south,east,north") from None
        return west, south, east, north

    def apply(self, query, db: Session, live: for_leads.LiveCells):
        unknown = set(self.signals) - set(SIGNAL_TYPES)
        if unknown:
            raise HTTPException(422, f"Unknown signal(s): {', '.join(sorted(unknown))}")
        bad_bands = set(self.need_band) - set(NEED_BANDS)
        if bad_bands:
            raise HTTPException(422, f"Unknown need_band(s): {', '.join(sorted(bad_bands))}")
        bad_cells = [c for c in self.cells if not geo.is_cell(c) or geo.cell_resolution(c) != 8]
        if bad_cells:
            raise HTTPException(422, f"cells must be H3 resolution-8 ids: {bad_cells[:5]}")
        allowed = self.cell_set(db, live)
        if allowed is not None:
            query = query.where(Property.h3_index.in_(allowed)) if allowed else query.where(false())
        if bounds := self.bounds():
            west, south, east, north = bounds
            query = query.where(
                Property.lat.between(south, north), Property.lon.between(west, east)
            )
        query = query.where(Lead.score >= self.min_score)
        for kind in self.signals:
            query = query.where(_has_signal(kind))
        if self.new_only:
            query = query.where(Lead.triggered_at >= _window())
        if self.zip:
            query = query.where(Property.situs_zip == self.zip)
        if self.status:
            query = query.where(Lead.status == self.status)
        if self.zone:
            query = query.where(Lead.load_zone == self.zone)
        return query


def _filters(
    min_score: float = 0,
    signals: Annotated[list[str], Query()] = [],  # noqa: B006 - FastAPI query list
    new_only: bool = False,
    zip: str | None = None,
    status: Status | None = None,
    zone: str | None = None,
    cells: Annotated[list[str], Query()] = [],  # noqa: B006 - FastAPI query list
    need_band: Annotated[list[str], Query()] = [],  # noqa: B006 - FastAPI query list
    alert: bool = False,
    forecast: bool = False,
    grid_stress: bool = False,
    bbox: str | None = None,
) -> LeadFilters:
    return LeadFilters(
        min_score=min_score,
        signals=signals,
        new_only=new_only,
        zip=zip,
        status=status,
        zone=zone,
        cells=cells,
        need_band=need_band,
        alert=alert,
        forecast=forecast,
        grid_stress=grid_stress,
        bbox=bbox,
    )


Filters = Annotated[LeadFilters, Depends(_filters)]


@router.get("/leads", response_model=LeadPage)
def list_leads(
    db: DB,
    filters: Filters,
    sort: Sort = "need",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Leads ranked by their Cell (Baseline Need), then the home (consumption, then Expected
    Value). Cell scores are joined at request time through the home's h3_index."""
    now = _now()
    live = for_leads.LiveCells(db, now)
    query = filters.apply(
        select(Lead, Property)
        .join(Property)
        .outerjoin(CellBaselineNeed, CellBaselineNeed.h3_index == Property.h3_index),
        db,
        live,
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(*_order(sort)).limit(limit).offset(offset)).all()
    blocks = for_leads.cell_blocks(db, {p.h3_index for _, p in rows if p.h3_index}, now)
    return {
        "total": total,
        "items": [_item(lead, prop, blocks.get(prop.h3_index)) for lead, prop in rows],
        "summary": _summary(db, query, total, live),
    }


def _order(sort: Sort) -> tuple:
    by_home = (Lead.annual_kwh.desc().nulls_last(), Lead.expected_value.desc().nulls_last())
    return (
        *{
            "need": (CellBaselineNeed.baseline_need.desc().nulls_last(), *by_home),
            "priority": (Lead.expected_value.desc().nulls_last(),),
            "value": (Lead.value.desc().nulls_last(),),
            "consumption": (Lead.annual_kwh.desc().nulls_last(),),
            "triggered_at": (Lead.triggered_at.desc().nulls_last(),),
        }[sort],
        Property.id,
    )


EXPORT_COLUMNS = (
    "owner_name",
    "mail_street",
    "mail_city",
    "mail_state",
    "mail_zip",
    "property_address",
    "property_city",
    "property_zip",
    "county",
)


@router.get("/leads/export.csv")
def export_leads(db: DB, filters: Filters, sort: Sort = "need"):
    """Every lead the filters allow, in list order, as a mailing list: the owner and the
    home's address, nothing we computed. Confidential owners never become leads."""
    query = filters.apply(
        select(
            Property.owner_name,
            Property.mail_address,
            Property.situs_address,
            Property.situs_city,
            Property.situs_zip,
            Property.county,
        )
        .select_from(Lead)
        .join(Property)
        .outerjoin(CellBaselineNeed, CellBaselineNeed.h3_index == Property.h3_index),
        db,
        for_leads.LiveCells(db, _now()),
    ).order_by(*_order(sort))

    def rows():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(EXPORT_COLUMNS)
        # Its own session: the request's may close before the stream ends.
        with SessionLocal() as stream_db:
            for owner, mail, street, city, zip_code, county in stream_db.execute(
                query.execution_options(yield_per=5_000)
            ):
                writer.writerow((owner, *split_mail_address(mail), street, city, zip_code, county))
                if buffer.tell() > 64_000:
                    yield buffer.getvalue()
                    buffer.seek(0)
                    buffer.truncate()
        yield buffer.getvalue()

    filename = f"leads-{_now():%Y-%m-%d}.csv"
    return StreamingResponse(
        rows(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _summary(db: Session, query, total: int, live: for_leads.LiveCells) -> dict:
    """The filtered set by Cell: one small aggregate, then the live sets applied to it."""
    filtered = query.subquery()
    per_cell = dict(
        db.execute(select(filtered.c.h3_index, func.count()).group_by(filtered.c.h3_index)).all()
    )
    per_cell.pop(None, None)
    needs = (
        dict(
            db.execute(
                select(CellBaselineNeed.h3_index, CellBaselineNeed.baseline_need).where(
                    CellBaselineNeed.h3_index.in_(per_cell)
                )
            ).all()
        )
        if per_cell
        else {}
    )
    weighted = [(needs[h], n) for h, n in per_cell.items() if needs.get(h) is not None]
    avg = sum(v * n for v, n in weighted) / sum(n for _, n in weighted) if weighted else None

    def count(cells: set[str]) -> int:
        return sum(n for h, n in per_cell.items() if h in cells)

    return {
        "leads": total,
        "avg_baseline_need": round(avg, 1) if avg is not None else None,
        "alert": count(live.alert) if per_cell else 0,
        "forecast": count(live.forecast) if per_cell else 0,
        "grid_stress": count(live.grid_stress) if per_cell else 0,
        "grid_state": for_leads.grid_state(db, live.now),
    }


# Above this many leads in view, the map gets grid cells instead of points.
MAX_MAP_POINTS = 5000


@router.get("/leads/geo")
def leads_geo(
    db: DB,
    filters: Filters,
    zoom: Annotated[float, Query(ge=0, le=24)] = 10,
):
    """GeoJSON for the map: lead points, or grid cells (count, avg score) when crowded.
    The viewport is the shared `bbox` filter, required here."""
    bounds = filters.bounds()
    if bounds is None:
        raise HTTPException(422, "bbox (west,south,east,north) is required")
    west, south, east, north = bounds
    in_view = filters.apply(
        select(Lead, Property).join(Property), db, for_leads.LiveCells(db, _now())
    ).subquery()
    total = db.scalar(select(func.count()).select_from(in_view))

    if total <= MAX_MAP_POINTS:
        rows = db.execute(
            select(
                in_view.c.property_id,
                in_view.c.lat,
                in_view.c.lon,
                in_view.c.score,
                in_view.c.situs_address,
                in_view.c.trigger,
            )
        ).all()
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r.lon, r.lat]},
                "properties": {
                    "id": r.property_id,
                    "score": r.score,
                    "address": r.situs_address,
                    "trigger": r.trigger,
                },
            }
            for r in rows
        ]
        return {
            "type": "FeatureCollection",
            "aggregated": False,
            "total": total,
            "features": features,
        }

    cell = 360 / 2**zoom / 8  # ~8 cells across a map tile
    gx, gy = func.floor(in_view.c.lon / cell), func.floor(in_view.c.lat / cell)
    cells = db.execute(
        select(
            func.count().label("n"),
            func.avg(in_view.c.score).label("score"),
            func.avg(in_view.c.lon).label("lon"),
            func.avg(in_view.c.lat).label("lat"),
        ).group_by(gx, gy)
    ).all()
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(c.lon), float(c.lat)]},
            "properties": {"count": c.n, "score": round(float(c.score), 1)},
        }
        for c in cells
    ]
    return {"type": "FeatureCollection", "aggregated": True, "total": total, "features": features}


def _detail(db: Session, lead_id: int) -> dict:
    row = db.execute(select(Lead, Property).join(Property).where(Lead.property_id == lead_id))
    found = row.first()
    if not found:
        raise HTTPException(404, f"Unknown lead {lead_id}")
    lead, prop = found
    total = sum(scoring.weights.values())
    cell = (
        for_leads.cell_blocks(db, {prop.h3_index}, _now()).get(prop.h3_index)
        if prop.h3_index
        else None
    )
    return {
        **_item(lead, prop, cell),
        # Owner name and mailing address are deliberately not exposed here.
        "account": prop.account,
        "market_value": prop.market_value,
        "heated_sqft": prop.heated_sqft,
        "year_built": prop.year_built,
        "bedrooms": prop.bedrooms,
        "full_baths": prop.full_baths,
        "half_baths": prop.half_baths,
        "stories": prop.stories,
        "consumption": lead.consumption,
        "lat": prop.lat,
        "lon": prop.lon,
        "first_seen_at": lead.first_seen_at,
        "scored_at": lead.scored_at,
        "drivers": [
            {
                "key": d.key,
                "label": d.label,
                "kind": "percentile" if d.key in PERCENTILE_DRIVERS else "flag",
                "weight": scoring.weights[d.key] / total,
                **lead.drivers[d.key],
            }
            for d in DRIVERS
            if d.key in lead.drivers
        ],
        "evidence": lead.signals,
    }


@router.get("/leads/{lead_id}", response_model=LeadDetail)
def get_lead(lead_id: int, db: DB):
    return _detail(db, lead_id)


@router.patch("/leads/{lead_id}", response_model=LeadDetail)
def update_lead(lead_id: int, body: StatusUpdate, db: DB):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, f"Unknown lead {lead_id}")
    lead.status = body.status
    db.commit()
    return _detail(db, lead_id)


@router.get("/sources", response_model=list[SourceStatus])
def list_sources(db: DB):
    out = []
    for source_id in SOURCES:
        runs = SourceRun.source_id == source_id
        last = db.scalar(
            select(SourceRun).where(runs).order_by(SourceRun.started_at.desc(), SourceRun.id.desc())
        )
        last_ok = db.scalar(
            select(func.max(SourceRun.finished_at)).where(runs, SourceRun.status == "success")
        )
        out.append(
            {
                "source_id": source_id,
                "status": last.status if last else None,
                "started_at": last.started_at if last else None,
                "finished_at": last.finished_at if last else None,
                "rows": last.rows if last else None,
                "inserted": last.inserted if last else None,
                "updated": last.updated if last else None,
                "error": last.error if last else None,
                "last_success_at": last_ok,
            }
        )
    return out
