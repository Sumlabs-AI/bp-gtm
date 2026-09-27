"""api.weather.gov access for NWS Alerts (public domain; a User-Agent is required).

Zone geometries (forecast `TXZ…` / county `TXC…`) rarely change, so they're cached on disk
under data/cache/nws-zones/ (gitignored) and fetched once.
"""

import json
import os
from collections.abc import Callable
from pathlib import Path

import httpx

from app.need.config import nws_alerts as config

ZONE_CACHE = Path(__file__).resolve().parents[3] / "data/cache/nws-zones"


def client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": config.user_agent, "Accept": "application/geo+json"},
        timeout=30,
        follow_redirects=True,
    )


def fetch_alerts(http: httpx.Client) -> dict[str, object]:
    return http.get(config.alerts_url).raise_for_status().json()


def zone_resolver(http: httpx.Client) -> Callable[[list[str]], list[dict]]:
    """zone URLs -> GeoJSON geometries, from the disk cache or api.weather.gov."""

    def resolve(zone_urls: list[str]) -> list[dict]:
        geometries = []
        for url in zone_urls:
            kind, ugc = url.rstrip("/").split("/")[-2:]
            path = ZONE_CACHE / f"{kind}-{ugc}.json"
            if not path.exists():
                zone = http.get(url).raise_for_status().json()
                if not zone.get("geometry"):
                    raise ValueError(f"zone {ugc} has no geometry")
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".part")  # atomic: a crash never leaves bad JSON
                tmp.write_text(json.dumps(zone["geometry"]))
                os.replace(tmp, path)
            geometries.append(json.loads(path.read_text()))
        return geometries

    return resolve


def grid_cell(http: httpx.Client, lat: float, lng: float) -> tuple[str, int, int]:
    """The NWS forecast grid cell (office, x, y) covering a point."""
    props = http.get(f"https://api.weather.gov/points/{lat:.4f},{lng:.4f}").raise_for_status()
    p = props.json()["properties"]
    return p["gridId"], p["gridX"], p["gridY"]


def fetch_gridpoint(http: httpx.Client, office: str, x: int, y: int) -> dict:
    return (
        http.get(f"https://api.weather.gov/gridpoints/{office}/{x},{y}").raise_for_status().json()
    )


def fetch_spc_outlooks(http: httpx.Client, urls: list[str]) -> list[dict]:
    return [http.get(url).raise_for_status().json() for url in urls]
