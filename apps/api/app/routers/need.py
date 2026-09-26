from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import geo
from app.db import get_db
from app.models import ForecastSignal, NwsAlert
from app.need.baseline import LIMITATIONS as BASELINE_LIMITATIONS
from app.need.baseline import METHOD as BASELINE_METHOD
from app.need.baseline import baseline_components
from app.need.config import forecast as forecast_config
from app.need.config import need
from app.need.live.forecast import COMPARISON
from app.need.live.forecast_store import active_forecast, forecast_status, most_severe_level
from app.need.live.grid import condition_summary, grid_live, latest_condition
from app.need.live.store import active_alerts, alert_status, most_severe_category
from app.need.ml import latest_propensity
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


class ForecastOut(BaseModel):
    """A Forecast Signal: our reading of NWS grid / SPC outlook data, not an NWS Alert."""

    source: str  # "nws_grid" | "spc_outlook"
    condition: str
    level: str
    comparison: str | None  # ">=" or "<=" against `threshold` (None for SPC)
    startAt: datetime  # noqa: N815
    endAt: datetime  # noqa: N815
    leadHours: float  # noqa: N815  (hours from now to start; negative when under way)
    peakValue: float | None  # noqa: N815
    unit: str | None
    threshold: float | None
    label: str | None  # SPC category (e.g. ENH)
    sourceUpdatedAt: datetime  # noqa: N815  (when NWS/SPC issued it)


class SpcFreshness(BaseModel):
    fetchedAt: datetime | None  # noqa: N815  (our last successful fetch)
    stale: bool


class GridFreshness(SpcFreshness):
    sourceUpdatedAt: datetime | None  # noqa: N815  (NWS forecast updateTime, not ours)


class ForecastFeed(BaseModel):
    resolution: int
    sourceCell: str  # noqa: N815  (the res-6 forecast point this Cell reads)
    horizonHours: int  # noqa: N815
    grid: GridFreshness
    spc: SpcFreshness
    signals: list[ForecastOut]


class GridConditionOut(BaseModel):
    """The ERCOT Grid Condition: official, as ERCOT declares it."""

    state: str | None
    title: str | None
    eeaLevel: int | None  # noqa: N815
    prcMw: int | None  # noqa: N815
    official: bool  # True only when ERCOT declares something other than normal
    sourceUpdatedAt: datetime | None  # noqa: N815
    fetchedAt: datetime | None  # noqa: N815
    stale: bool


class LatestPrice(BaseModel):
    price: float
    intervalStart: datetime  # noqa: N815


class GridPrices(BaseModel):
    loadZone: str | None  # noqa: N815
    latestRt: LatestPrice | None  # noqa: N815
    stale: bool


class GridStressSignal(BaseModel):
    """Our reading of ERCOT data crossing one of our thresholds (not an ERCOT declaration)."""

    type: str  # low_reserves | tight_margin | rt_price_spike | dam_price_spike
    category: str  # "reliability" | "market"
    value: float
    threshold: float
    unit: str
    at: datetime | None
    message: str
    hours: int | None = None  # day-ahead spikes: hours at or above the threshold


class LiveGrid(BaseModel):
    condition: GridConditionOut
    prices: GridPrices
    stressSignals: list[GridStressSignal]  # noqa: N815
    notes: list[str]


class LiveWeather(BaseModel):
    alerts: AlertFeed
    forecast: ForecastFeed


class Live(BaseModel):
    weather: LiveWeather
    grid: LiveGrid


class BaselineInputs(BaseModel):
    observedOutageExposure: float | None  # noqa: N815
    weatherNeed: float | None  # noqa: N815


class BaselineContext(BaseModel):
    utilityReliabilityNeed: float | None  # noqa: N815  (shown, not combined)


class BaselineOut(BaseModel):
    """Baseline Need: structural reason for backup power. Not Live Need, not Propensity,
    not the GTM score."""

    baselineNeed: float | None  # noqa: N815  (Texas res-6 percentile)
    raw: float | None
    dominantDriver: Literal["outage", "weather", "both"] | None  # noqa: N815
    inputs: BaselineInputs
    context: BaselineContext
    method: str
    limitations: list[str]
    notes: list[str]


class PropensityOut(BaseModel):
    """The ML workstream's Propensity Score for this Cell (latest prediction). Not Need,
    not Opportunity."""

    score: float
    modelVersion: str  # noqa: N815
    featureVersion: str  # noqa: N815  (Need Feature Version it was scored against)
    scoredAt: datetime  # noqa: N815
    importedAt: datetime  # noqa: N815


class CellDetail(BaseModel):
    h3: str
    resolution: int
    center: LatLng
    loadZone: str | None  # noqa: N815
    needScore: float | None  # noqa: N815  (camelCase is the API contract)
    baseline: BaselineOut | None
    propensity: PropensityOut | None
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


def _forecast_out(s: ForecastSignal, now: datetime) -> ForecastOut:
    return ForecastOut(
        source=s.source,
        condition=s.condition,
        level=s.level,
        comparison=COMPARISON[forecast_config.conditions[s.condition].direction]
        if s.source == "nws_grid"
        else None,
        startAt=s.start_at,
        endAt=s.end_at,
        leadHours=round((s.start_at - now).total_seconds() / 3600, 1),
        peakValue=s.peak_value,
        unit=s.unit,
        threshold=s.threshold,
        label=s.label,
        sourceUpdatedAt=s.source_updated_at,
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
    forecasts = active_forecast(db, cells, now)
    grid = grid_live(db, cells, now)
    baseline = baseline_components(db, cells)
    propensity = latest_propensity(db, [c.h3_index for c in cells])
    return {
        "type": "FeatureCollection",
        # ERCOT-wide, so given once (also when no Cell is in view) for the map's status chip.
        "grid": condition_summary(latest_condition(db, now), now),
        "features": [
            {
                "type": "Feature",
                "id": c.h3_index,
                "geometry": geo.cell_to_polygon(c.h3_index),
                "properties": {
                    "h3": c.h3_index,
                    "needScore": None,
                    "baselineNeed": b.baseline_need if (b := baseline[c.h3_index]) else None,
                    "propensityScore": p.propensity_score
                    if (p := propensity[c.h3_index])
                    else None,
                    "outageNeed": (outage[c.h3_index] or {}).get("score"),
                    "weatherNeed": (weather[c.h3_index] or {}).get("score"),
                    "activeAlerts": len(alerts[c.h3_index]),
                    "activeAlertCategory": most_severe_category(alerts[c.h3_index]),
                    "activeForecastSignals": len(forecasts[c.h3_index]),
                    "forecastLevel": most_severe_level(forecasts[c.h3_index]),
                    "gridState": grid[c.h3_index]["condition"]["state"],
                    "activeGridStressSignals": len(grid[c.h3_index]["stressSignals"]),
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
    b = baseline_components(db, [cell])[cell.h3_index]
    p = latest_propensity(db, [cell.h3_index])[cell.h3_index]
    reliability = ((outage or {}).get("utilityReliabilityNeed") or {}).get("score")
    point = geo.cell_to_parent(cell.h3_index, forecast_config.resolution)
    status = forecast_status(db, [point], now)
    grid = status["grid"].get(point, {"fetched_at": None, "source_updated_at": None, "stale": True})
    return CellDetail(
        h3=cell.h3_index,
        resolution=cell.resolution,
        center=LatLng(lat=cell.center_lat, lng=cell.center_lng),
        loadZone=cell.load_zone,
        needScore=None,
        baseline=BaselineOut(
            baselineNeed=b.baseline_need,
            raw=b.raw,
            dominantDriver=b.dominant_driver,
            inputs=BaselineInputs(
                observedOutageExposure=b.outage_input, weatherNeed=b.weather_input
            ),
            context=BaselineContext(utilityReliabilityNeed=reliability),
            method=BASELINE_METHOD,
            limitations=BASELINE_LIMITATIONS,
            notes=b.notes,
        )
        if b
        else None,
        propensity=PropensityOut(
            score=p.propensity_score,
            modelVersion=p.model_version,
            featureVersion=p.feature_version,
            scoredAt=p.scored_at,
            importedAt=p.imported_at,
        )
        if p
        else None,
        components=components,
        live=Live(
            weather=LiveWeather(
                alerts=AlertFeed(
                    fetchedAt=fetched_at,
                    stale=stale,
                    signals=[_alert_out(s) for s in active_alerts(db, [cell], now)[cell.h3_index]],
                ),
                forecast=ForecastFeed(
                    resolution=forecast_config.resolution,
                    sourceCell=point,
                    horizonHours=forecast_config.horizon_hours,
                    grid=GridFreshness(
                        fetchedAt=grid["fetched_at"],
                        sourceUpdatedAt=grid["source_updated_at"],
                        stale=grid["stale"],
                    ),
                    spc=SpcFreshness(
                        fetchedAt=status["spc"]["fetched_at"], stale=status["spc"]["stale"]
                    ),
                    signals=[
                        _forecast_out(s, now)
                        for s in active_forecast(db, [cell], now)[cell.h3_index]
                    ],
                ),
            ),
            grid=LiveGrid(**grid_live(db, [cell], now)[cell.h3_index]),
        ),
    )
