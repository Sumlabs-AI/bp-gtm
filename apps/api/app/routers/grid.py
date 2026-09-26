from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.grid.config import battery, scoring
from app.grid.metrics import DRIVERS, primary_reason
from app.grid.zones import ZONES_BY_CODE, ZONES_GEOJSON
from app.models import GridZoneMetrics

router = APIRouter(prefix="/grid", tags=["grid"])

DB = Annotated[Session, Depends(get_db)]


class DriverOut(BaseModel):
    key: str
    label: str
    unit: str
    weight: float
    score: float
    value: float
    explanation: str


class ZoneSummary(BaseModel):
    code: str
    name: str
    description: str
    on_map: bool
    rank: int
    grid_value_score: float
    primary_reason: str
    drivers: list[DriverOut]


class ZoneDetail(ZoneSummary):
    period_start: datetime
    period_end: datetime
    metrics: dict[str, float]
    series: dict
    assumptions: dict


def _summary(row: GridZoneMetrics, rank: int) -> dict:
    zone = ZONES_BY_CODE[row.settlement_point]
    total = sum(scoring.weights.values())
    return {
        "code": zone.code,
        "name": zone.name,
        "description": zone.description,
        "on_map": zone.on_map,
        "rank": rank,
        "grid_value_score": row.grid_value_score,
        "primary_reason": primary_reason(row.scores, scoring.weights),
        "drivers": [
            {
                "key": d.key,
                "label": d.label,
                "unit": d.unit,
                "weight": scoring.weights[d.key] / total,
                "score": row.scores[d.key],
                "value": row.metrics[d.metric],
                "explanation": d.explain.format(v=row.metrics[d.metric]),
            }
            for d in DRIVERS
        ],
    }


def _ranked(db: Session) -> list[GridZoneMetrics]:
    return list(
        db.scalars(select(GridZoneMetrics).order_by(GridZoneMetrics.grid_value_score.desc()))
    )


@router.get("/zones.geojson")
def zones_geojson():
    """Approximate load zone boundaries (see scripts/build_zone_geojson.py)."""
    return FileResponse(ZONES_GEOJSON, media_type="application/geo+json")


@router.get("/zones", response_model=list[ZoneSummary])
def list_zones(db: DB):
    return [_summary(row, i + 1) for i, row in enumerate(_ranked(db))]


@router.get("/zones/{code}", response_model=ZoneDetail)
def get_zone(code: str, db: DB):
    for i, row in enumerate(_ranked(db)):
        if row.settlement_point == code:
            return {
                **_summary(row, i + 1),
                "period_start": row.period_start,
                "period_end": row.period_end,
                "metrics": row.metrics,
                "series": row.series,
                "assumptions": {"battery": battery.model_dump(), "scoring": scoring.model_dump()},
            }
    raise HTTPException(404, f"Unknown zone {code}")
