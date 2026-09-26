"""Live Weather Signals from NWS alert Snapshots.

A Snapshot is one complete fetch of all active NWS alerts for Texas. Only a successful,
complete Snapshot changes signals: allowlisted alerts are upserted, and signals missing from
it are superseded (cancelled, replaced or ended by NWS). Any failure (fetch, parse, a zone
geometry) logs a failed Snapshot and leaves every signal untouched.
"""

from collections.abc import Callable
from datetime import datetime

from geoalchemy2.shape import from_shape
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import LiveWeatherSignal, LiveWeatherSnapshot
from app.need.config import live_weather as config

Fetch = Callable[[], dict]
ResolveZones = Callable[[list[str]], list[dict]]  # zone URLs -> GeoJSON geometries


def _time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _multipolygon(geometry: BaseGeometry) -> MultiPolygon:
    polygons = [g for g in getattr(geometry, "geoms", [geometry]) if isinstance(g, Polygon)]
    polygons += [
        p for g in getattr(geometry, "geoms", []) if isinstance(g, MultiPolygon) for p in g.geoms
    ]
    if not polygons:
        raise ValueError(f"no polygon area in {geometry.geom_type}")
    return MultiPolygon(polygons)


def parse(payload: dict, resolve_zones: ResolveZones) -> list[dict]:
    """Allowlisted alerts as signal rows (without ingestion times). Raises on anything
    incomplete, so the caller can treat the whole Snapshot as failed."""
    signals = []
    for feature in payload["features"]:
        p = feature["properties"]
        category = config.categories.get(p["event"])
        if category is None:
            continue
        zone_urls = p.get("affectedZones") or []
        if feature.get("geometry"):
            area, source = shape(feature["geometry"]), "alert"
        else:
            area = unary_union([shape(g) for g in resolve_zones(zone_urls)])
            source = "zones"
        signals.append(
            {
                "id": p["id"],
                "event": p["event"],
                "category": category,
                "severity": p.get("severity"),
                "certainty": p.get("certainty"),
                "urgency": p.get("urgency"),
                "message_type": p.get("messageType"),
                "headline": p.get("headline"),
                "sender": p.get("senderName"),
                "zones": [url.rsplit("/", 1)[1] for url in zone_urls],
                "sent_at": _time(p.get("sent")),
                "effective_at": _time(p["effective"]),
                "onset_at": _time(p.get("onset")),
                "expires_at": _time(p["expires"]),
                "ends_at": _time(p.get("ends")),
                "geometry": from_shape(_multipolygon(area), srid=4326),
                "geometry_source": source,
            }
        )
    return signals


def refresh(db: Session, fetch: Fetch, resolve_zones: ResolveZones, now: datetime):
    """Take one Snapshot at `now` and apply it if complete. The caller commits."""
    snapshot = LiveWeatherSnapshot(fetched_at=now, succeeded=False)
    try:
        payload = fetch()
        signals = parse(payload, resolve_zones)
    except Exception as exc:  # any failure: log it, change no signal
        snapshot.error = f"{type(exc).__name__}: {exc}"
        db.add(snapshot)
        db.flush()
        return snapshot

    if signals:
        stmt = insert(LiveWeatherSignal).values(
            [{**s, "first_seen_at": now, "last_seen_at": now} for s in signals]
        )
        kept = {c: stmt.excluded[c] for c in signals[0] if c != "id"}
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={**kept, "last_seen_at": now, "superseded_at": None},
            )
        )
    superseded = db.execute(
        update(LiveWeatherSignal)
        .where(
            LiveWeatherSignal.superseded_at.is_(None),
            LiveWeatherSignal.id.not_in([s["id"] for s in signals]),
        )
        .values(superseded_at=now)
    ).rowcount
    snapshot.succeeded = True
    snapshot.source_updated_at = _time(payload.get("updated"))
    snapshot.alerts_total = len(payload["features"])
    snapshot.signals_kept = len(signals)
    snapshot.superseded = superseded
    db.add(snapshot)
    db.flush()
    return snapshot
