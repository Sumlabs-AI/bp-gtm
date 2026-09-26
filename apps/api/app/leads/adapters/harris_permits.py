"""Harris County issued permits (ArcGIS FeatureServer).

Layer: Permits/IssuedPermits/FeatureServer/0 on gis.hctx.net. Records are points.
ISSUEDDATE is epoch milliseconds at midnight Central Standard Time (the layer
does not observe daylight saving). FULLADDRESS looks like
"15948 Woodland Hills Dr Humble TX 77346"; the zip, and usually the city, have
to be split out of that string. Some rows omit the city or use a non-TX state
token.

fetch() pages every issued permit in the last LOOKBACK_DAYS with resultOffset.
parse() keeps solar, EV charger, and new single-family rows only.
"""

import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pandas as pd

from app.leads.adapters.permit_categories import classify
from app.leads.address import zip5
from app.leads.frames import PERMIT_CATEGORIES, PERMIT_COLUMNS

SOURCE_ID = "harris_county_issued_permits"
LOOKBACK_DAYS = 3 * 365

LAYER_URL = (
    "https://www.gis.hctx.net/arcgishcpid/rest/services/Permits/IssuedPermits/FeatureServer/0"
)
_QUERY_URL = f"{LAYER_URL}/query"
_UA = {"User-Agent": "base-power-gtm/0.1"}
_TIMEOUT = 180
# Layer time zone is Central Standard Time and respectsDaylightSaving is false.
_CST = timezone(timedelta(hours=-6))
_KEEP = PERMIT_CATEGORIES - {"other"}
_OUT_FIELDS = ",".join(
    [
        "OBJECTID",
        "PROJECTNUMBER",
        "PROJECTNAME",
        "FULLADDRESS",
        "PERMITNUMBER",
        "PERMITNAME",
        "ISSUEDDATE",
    ]
)
_SUFFIXES = {
    "ST",
    "STREET",
    "AVE",
    "AVENUE",
    "DR",
    "DRIVE",
    "RD",
    "ROAD",
    "LN",
    "LANE",
    "CT",
    "COURT",
    "CIR",
    "CIRCLE",
    "BLVD",
    "BOULEVARD",
    "PL",
    "PLACE",
    "TRL",
    "TRAIL",
    "PKWY",
    "PARKWAY",
    "HWY",
    "HIGHWAY",
    "FWY",
    "FREEWAY",
    "EXPY",
    "EXPRESSWAY",
    "TER",
    "TERRACE",
    "CV",
    "COVE",
    "WAY",
    "LOOP",
    "BND",
    "BEND",
    "XING",
    "CROSSING",
    "PT",
    "POINT",
    "RUN",
    "PATH",
    "PASS",
    "PLZ",
    "PLAZA",
    "ALY",
    "ALLEY",
    "ROW",
    "PIKE",
    "RDG",
    "RIDGE",
}
_UNITS = {
    "STE",
    "SUITE",
    "BLDG",
    "BUILDING",
    "TRLR",
    "TRAILER",
    "APT",
    "APARTMENT",
    "UNIT",
    "NO",
    "LOT",
    "SPC",
    "FL",
    "FLOOR",
    "RM",
    "ROOM",
}


def fingerprint() -> str:
    """Max ISSUEDDATE (epoch ms) and feature count. One statistics query."""
    payload = _get(
        {
            "where": "1=1",
            "outStatistics": json.dumps(
                [
                    {
                        "statisticType": "max",
                        "onStatisticField": "ISSUEDDATE",
                        "outStatisticFieldName": "max_issued",
                    },
                    {
                        "statisticType": "count",
                        "onStatisticField": "OBJECTID",
                        "outStatisticFieldName": "cnt",
                    },
                ]
            ),
            "f": "json",
        }
    )
    attrs = payload["features"][0]["attributes"]
    return f"{attrs.get('max_issued')}:{attrs.get('cnt')}"


def fetch(raw_dir: Path) -> list[Path]:
    """Download issued permits from the lookback window, one JSON page per file."""
    page_size = _max_record_count()
    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
    where = f"ISSUEDDATE >= DATE '{cutoff.isoformat()}'"
    paths: list[Path] = []
    offset = 0
    while True:
        payload = _get(
            {
                "where": where,
                "outFields": _OUT_FIELDS,
                "returnGeometry": "true",
                "outSR": "4326",
                "orderByFields": "OBJECTID",
                "resultOffset": str(offset),
                "resultRecordCount": str(page_size),
                "f": "json",
            }
        )
        path = raw_dir / f"issued_{offset:07d}.json"
        path.write_text(json.dumps(payload))
        paths.append(path)
        features = payload.get("features") or []
        if not features or not payload.get("exceededTransferLimit"):
            break
        offset += len(features)
    return paths


def parse(paths: list[Path]) -> pd.DataFrame:
    """Parse fetched query pages into the permit frame. No network."""
    records: list[dict] = []
    for path in paths:
        payload = json.loads(path.read_text())
        wkid = _wkid(payload)
        for feature in payload.get("features") or []:
            row = _row(feature, wkid)
            if row is not None:
                records.append(row)
    return _frame(records)


def _get(params: dict) -> dict:
    # High offsets on this layer occasionally stall; retry the same page.
    last_error: Exception | None = None
    for delay in (0, 2, 5):
        if delay:
            time.sleep(delay)
        try:
            resp = httpx.get(_QUERY_URL, params=params, headers=_UA, timeout=_TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
            break
        except httpx.TransportError as exc:
            last_error = exc
    else:
        raise last_error or RuntimeError("Harris permits query failed")
    if "error" in payload:
        message = payload["error"].get("message") or "Harris permits query failed"
        raise RuntimeError(message)
    return payload


def _max_record_count() -> int:
    resp = httpx.get(LAYER_URL, params={"f": "json"}, headers=_UA, timeout=_TIMEOUT)
    resp.raise_for_status()
    return int(resp.json().get("maxRecordCount") or 2000)


def _wkid(payload: dict) -> int | None:
    ref = payload.get("spatialReference") or {}
    wkid = ref.get("latestWkid") or ref.get("wkid")
    return int(wkid) if wkid is not None else None


def _row(feature: dict, wkid: int | None) -> dict | None:
    attrs = feature.get("attributes") or {}
    description = _join(attrs.get("PERMITNAME"), attrs.get("PROJECTNAME"))
    category = classify(description)
    if category not in _KEEP:
        return None
    street, city, zip_code = _split_address(attrs.get("FULLADDRESS"))
    lon, lat = _lon_lat(feature, wkid)
    permit_id = _clean(attrs.get("PERMITNUMBER")) or _clean(attrs.get("PROJECTNUMBER"))
    return {
        "source": SOURCE_ID,
        "permit_id": permit_id,
        "address": street,
        "city": city,
        "zip": zip_code,
        "issued_date": _issued(attrs.get("ISSUEDDATE")),
        "category": category,
        "description": description,
        "lat": lat,
        "lon": lon,
    }


def _lon_lat(feature: dict, wkid: int | None) -> tuple[float | None, float | None]:
    # fetch() asks for outSR=4326. Ignore any other spatial reference.
    if wkid != 4326:
        return None, None
    geom = feature.get("geometry") or {}
    x, y = geom.get("x"), geom.get("y")
    if x is None or y is None:
        return None, None
    return float(x), float(y)


def _issued(value: object) -> date | None:
    if value is None or _missing(value):
        return None
    moment = datetime.fromtimestamp(float(value) / 1000, tz=_CST)
    return moment.date()


def _split_address(full: object) -> tuple[str | None, str | None, str | None]:
    """Split '123 Oak St Humble TX 77346' into street, city, zip.

    City is whatever remains after the last street suffix and a trailing unit
    ('Ste C', 'No. 2'). Rows with no suffix keep the whole left side as the
    street and leave city empty.
    """
    text = _clean(full)
    if not text:
        return None, None, None
    text = re.sub(r"\s+", " ", text.replace(",", " ")).strip()
    match = re.search(
        r"^(?P<left>.+?)(?:\s+(?P<state>[A-Za-z]{2}))?\s+(?P<zip>\d{5})(?:-\d{4})?\s*$",
        text,
    )
    if not match:
        return text, None, None
    left = match.group("left").strip()
    zip_code = zip5(match.group("zip"))
    tokens = left.split()
    suffix_at = None
    for index, token in enumerate(tokens):
        if _key(token) in _SUFFIXES:
            suffix_at = index
    if suffix_at is None:
        return left, None, zip_code
    cursor = suffix_at + 1
    while cursor < len(tokens) and _key(tokens[cursor]) in _UNITS:
        cursor += 2 if cursor + 1 < len(tokens) else 1
    city = " ".join(tokens[cursor:]).strip() or None
    street = " ".join(tokens[:cursor]) or None
    return street, city, zip_code


def _key(token: str) -> str:
    return token.upper().rstrip(".")


def _join(*parts: object) -> str:
    return " | ".join(text for part in parts if (text := _clean(part)))


def _clean(value: object) -> str | None:
    if value is None or _missing(value):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text or None


def _missing(value: object) -> bool:
    return isinstance(value, float) and pd.isna(value)


def _frame(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame.from_records(records, columns=PERMIT_COLUMNS)
    df["issued_date"] = _as_dates(df["issued_date"])
    return df[PERMIT_COLUMNS]


def _as_dates(values: pd.Series) -> list[date | None]:
    out: list[date | None] = []
    for value in values:
        if value is None or _missing(value):
            out.append(None)
        elif isinstance(value, datetime):
            out.append(value.date())
        elif isinstance(value, date):
            out.append(value)
        else:
            out.append(None)
    return out
