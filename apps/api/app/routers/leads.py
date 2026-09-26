from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.leads.config import scoring
from app.leads.pipeline import SOURCES
from app.leads.scoring import DRIVERS
from app.models import Lead, Property, SourceRun

router = APIRouter(tags=["leads"])

DB = Annotated[Session, Depends(get_db)]
Status = Literal["new", "reviewed", "qualified", "excluded"]
PERCENTILE_DRIVERS = {"home_size", "home_value"}
SIGNAL_TYPES = ("solar", "ev_charger", "new_home", "new_owner", "new_meter", "pool")


class BatteryValue(BaseModel):
    value: float  # $/yr, battery trading on day-ahead plans over the last year
    ceiling: float  # $/yr with perfect hindsight: the most it could have earned
    low: float | None  # worst full calendar year
    low_year: int | None
    high: float | None  # best full calendar year
    high_year: int | None


class LeadItem(BaseModel):
    id: int
    address: str | None
    city: str | None
    zip: str | None
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
    expected_value: float | None  # score/100 × value: the default ranking


class LeadPage(BaseModel):
    total: int
    items: list[LeadItem]


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
    county: str
    account: str
    market_value: float | None
    heated_sqft: float | None
    year_built: int | None
    first_seen_at: datetime
    scored_at: datetime
    lat: float | None
    lon: float | None


class LeadSummary(BaseModel):
    properties: int
    leads: int
    new_this_week: int
    by_signal: dict[str, int]
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


def _item(lead: Lead, prop: Property) -> dict:
    return {
        "id": prop.id,
        "address": prop.situs_address,
        "city": prop.situs_city,
        "zip": prop.situs_zip,
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
        "last_scored_at": db.scalar(select(func.max(Lead.scored_at))),
    }


class LeadFilters(BaseModel):
    """Filters shared by the list and the map."""

    min_score: float = 0
    signals: list[str] = []
    new_only: bool = False
    zip: str | None = None
    status: Status | None = None

    def apply(self, query):
        unknown = set(self.signals) - set(SIGNAL_TYPES)
        if unknown:
            raise HTTPException(422, f"Unknown signal(s): {', '.join(sorted(unknown))}")
        query = query.where(Lead.score >= self.min_score)
        for kind in self.signals:
            query = query.where(_has_signal(kind))
        if self.new_only:
            query = query.where(Lead.triggered_at >= _window())
        if self.zip:
            query = query.where(Property.situs_zip == self.zip)
        if self.status:
            query = query.where(Lead.status == self.status)
        return query


def _filters(
    min_score: float = 0,
    signals: Annotated[list[str], Query()] = [],  # noqa: B006 - FastAPI query list
    new_only: bool = False,
    zip: str | None = None,
    status: Status | None = None,
) -> LeadFilters:
    return LeadFilters(
        min_score=min_score, signals=signals, new_only=new_only, zip=zip, status=status
    )


Filters = Annotated[LeadFilters, Depends(_filters)]


@router.get("/leads", response_model=LeadPage)
def list_leads(
    db: DB,
    filters: Filters,
    sort: Literal["priority", "score", "value", "triggered_at"] = "priority",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = filters.apply(select(Lead, Property).join(Property))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    order = {
        "priority": Lead.expected_value.desc().nulls_last(),
        "score": Lead.score.desc(),
        "value": Lead.value.desc().nulls_last(),
        "triggered_at": Lead.triggered_at.desc().nulls_last(),
    }[sort]
    rows = db.execute(query.order_by(order, Property.id).limit(limit).offset(offset)).all()
    return {"total": total, "items": [_item(lead, prop) for lead, prop in rows]}


# Above this many leads in view, the map gets grid cells instead of points.
MAX_MAP_POINTS = 5000


@router.get("/leads/geo")
def leads_geo(
    db: DB,
    filters: Filters,
    bbox: Annotated[str, Query(description="west,south,east,north in degrees")],
    zoom: Annotated[float, Query(ge=0, le=24)] = 10,
):
    """GeoJSON for the map: lead points, or grid cells (count, avg score) when crowded."""
    try:
        west, south, east, north = (float(v) for v in bbox.split(","))
    except ValueError:
        raise HTTPException(422, "bbox must be west,south,east,north") from None
    in_view = filters.apply(
        select(Lead, Property)
        .join(Property)
        .where(Property.lat.between(south, north), Property.lon.between(west, east))
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
    return {
        **_item(lead, prop),
        # Owner name and mailing address are deliberately not exposed here.
        "county": prop.county,
        "account": prop.account,
        "market_value": prop.market_value,
        "heated_sqft": prop.heated_sqft,
        "year_built": prop.year_built,
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
