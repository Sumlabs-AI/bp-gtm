from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import geo
from app.db import get_db
from app.need.config import need
from app.need.outage.component import outage_components
from app.need.store import cells_in_viewport, get_cell

router = APIRouter(prefix="/need", tags=["need"])

DB = Annotated[Session, Depends(get_db)]


class LatLng(BaseModel):
    lat: float
    lng: float


class CellDetail(BaseModel):
    h3: str
    resolution: int
    center: LatLng
    loadZone: str | None  # noqa: N815
    needScore: float | None  # noqa: N815  (camelCase is the API contract)
    components: dict[str, Any]


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
    outage = outage_components(db, cells, date.today())
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
    outage = outage_components(db, [cell], date.today())[cell.h3_index]
    return CellDetail(
        h3=cell.h3_index,
        resolution=cell.resolution,
        center=LatLng(lat=cell.center_lat, lng=cell.center_lng),
        loadZone=cell.load_zone,
        needScore=None,
        components={"outage": outage} if outage else {},
    )
