from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import geo
from app.db import get_db
from app.models import NwsAlert
from app.need.config import need
from app.need.live.store import active_alerts, alert_status, most_severe_category
from app.need.outage.component import outage_components
from app.need.store import cells_in_viewport, get_cell
from app.need.weather.component import weather_components

router = APIRouter(prefix="/need", tags=["need"])

DB = Annotated[Session, Depends(get_db)]


class LatLng(BaseModel):
    lat: float
    lng: float


class AlertOut(BaseModel):
    """An official NWS alert (never to be confused with our derived Forecast Signals)."""

    id: str
    event: str
    category: str
    severity: str | None
    certainty: str | None
    urgency: str | None
    headline: str | None
    effectiveAt: datetime  # noqa: N815
    endsAt: datetime  # noqa: N815  (NWS `ends`, or `expires` when there is none)
    geometrySource: str  # noqa: N815  ("alert" polygon or built from NWS "zones")
    firstSeenAt: datetime  # noqa: N815
    lastSeenAt: datetime  # noqa: N815


class AlertFeed(BaseModel):
    fetchedAt: datetime | None  # noqa: N815  (last successful NWS alert Snapshot)
    stale: bool
    signals: list[AlertOut]


class LiveWeather(BaseModel):
    alerts: AlertFeed


class Live(BaseModel):
    weather: LiveWeather


class CellDetail(BaseModel):
    h3: str
    resolution: int
    center: LatLng
    loadZone: str | None  # noqa: N815
    needScore: float | None  # noqa: N815  (camelCase is the API contract)
    components: dict[str, Any]
    live: Live


def _alert_out(s: NwsAlert) -> AlertOut:
    return AlertOut(
        id=s.id,
        event=s.event,
        category=s.category,
        severity=s.severity,
        certainty=s.certainty,
        urgency=s.urgency,
        headline=s.headline,
        effectiveAt=s.effective_at,
        endsAt=s.ends,
        geometrySource=s.geometry_source,
        firstSeenAt=s.first_seen_at,
        lastSeenAt=s.last_seen_at,
    )


def _bounds(bbox: str) -> tuple[float, float, float, float]:
    try:
        west, south, east, north = (float(v) for v in bbox.split(","))
    except ValueError:
        raise HTTPException(422, "bbox must be west,south,east,north") from None
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise HTTPException(422, "bbox must be west,south,east,north in degrees")
    return west, south, east, north


@router.get("/cells")
def list_cells(db: DB, bbox: Annotated[str, Query(description="west,south,east,north in degrees")]):
    """GeoJSON Cells intersecting the viewport (for the map)."""
    cells = cells_in_viewport(db, *_bounds(bbox), limit=need.viewport_max_cells)
    if cells is None:
        raise HTTPException(400, "Viewport contains too many H3 cells. Zoom in to continue.")
    now = datetime.now(UTC)
    outage = outage_components(db, cells, now.date())
    weather = weather_components(db, cells)
    alerts = active_alerts(db, cells, now)
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": c.h3_index,
                "geometry": geo.cell_to_polygon(c.h3_index),
                "properties": {
                    "h3": c.h3_index,
                    "needScore": None,
                    "outageNeed": (outage[c.h3_index] or {}).get("score"),
                    "weatherNeed": (weather[c.h3_index] or {}).get("score"),
                    "activeAlerts": len(alerts[c.h3_index]),
                    "activeAlertCategory": most_severe_category(alerts[c.h3_index]),
                },
            }
            for c in cells
        ],
    }


@router.get("/cells/{h3_index}", response_model=CellDetail)
def cell_detail(db: DB, h3_index: str):
    cell = get_cell(db, h3_index) if geo.is_cell(h3_index) else None
    if cell is None:
        raise HTTPException(404, f"Unknown cell {h3_index}")
    now = datetime.now(UTC)
    outage = outage_components(db, [cell], now.date())[cell.h3_index]
    weather = weather_components(db, [cell])[cell.h3_index]
    components = {name: c for name, c in (("outage", outage), ("weather", weather)) if c}
    fetched_at, stale = alert_status(db, now)
    return CellDetail(
        h3=cell.h3_index,
        resolution=cell.resolution,
        center=LatLng(lat=cell.center_lat, lng=cell.center_lng),
        loadZone=cell.load_zone,
        needScore=None,
        components=components,
        live=Live(
            weather=LiveWeather(
                alerts=AlertFeed(
                    fetchedAt=fetched_at,
                    stale=stale,
                    signals=[_alert_out(s) for s in active_alerts(db, [cell], now)[cell.h3_index]],
                )
            )
        ),
    )
