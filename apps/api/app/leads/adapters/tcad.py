"""Travis Central Appraisal District records, from Travis County's public TCAD parcel layer.

Layer: Boundaries_and_Jurisdictions/TCAD/MapServer/0 on gis.traviscountytx.gov, a monthly
copy of TCAD's parcels (1,000 rows per page). Only state class A1 (single-family) rows are
fetched: the only ones that can become leads (~287k).

The layer has no exemption codes and no living area. Owner-occupied (`homestead`) is
inferred as in ml/parcels/normalize.py: the owner's mailing address contains the property's
house number and first street word. Heated sqft, bedrooms, baths, stories, solar and pool
stay unknown.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pandas as pd

from app.leads.address import zip5
from app.leads.frames import PROPERTY_COLUMNS

SOURCE_ID = "tcad"
LAYER_URL = (
    "https://gis.traviscountytx.gov/server1/rest/services/"
    "Boundaries_and_Jurisdictions/TCAD/MapServer/0"
)
WHERE = "land_state_cd = 'A1'"
FIELDS = [
    "PROP_ID",
    "situs_num",
    "situs_street_prefx",
    "situs_street",
    "situs_street_suffix",
    "situs_city",
    "situs_zip",
    "py_owner_name",
    "py_address",
    "land_state_cd",
    "market_value",
    "F1year_imprv",
]
PAGE = 1_000
_UA = {"User-Agent": "base-power-gtm/0.1"}
_TIMEOUT = 120


def _query(client: httpx.Client, **params) -> dict:
    # POST: a page of 1,000 object ids is too long for a GET URL.
    resp = client.post(f"{LAYER_URL}/query", data={"f": "json", **params}, timeout=_TIMEOUT)
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise ValueError(f"TCAD layer error: {body['error']}")
    return body


def fingerprint() -> str:
    """Row count and newest edit: the layer is replaced monthly."""
    with httpx.Client(headers=_UA) as client:
        count = _query(client, where=WHERE, returnCountOnly="true")["count"]
        info = client.get(LAYER_URL, params={"f": "json"}, timeout=_TIMEOUT).json()
    return f"{count}:{(info.get('editingInfo') or {}).get('lastEditDate', '')}"


def fetch_pages(raw_dir: Path, fields: list[str], geometry: bool, workers: int = 6) -> list[Path]:
    """Every A1 row, one JSON file per page of object ids (geometry in WGS84 if asked)."""
    with httpx.Client(headers=_UA) as client:
        ids = sorted(_query(client, where=WHERE, returnIdsOnly="true")["objectIds"])
        chunks = [ids[i : i + PAGE] for i in range(0, len(ids), PAGE)]

        def page(n: int) -> Path:
            body = _query(
                client,
                objectIds=",".join(map(str, chunks[n])),
                outFields=",".join(fields),
                returnGeometry="true" if geometry else "false",
                outSR=4326,
                geometryPrecision=6,
            )
            path = raw_dir / f"page_{n:04d}.json"
            path.write_text(json.dumps(body["features"]))
            return path

        with ThreadPoolExecutor(workers) as pool:
            return list(pool.map(page, range(len(chunks))))


def fetch(raw_dir: Path) -> list[Path]:
    return fetch_pages(raw_dir, FIELDS, geometry=False)


def owner_occupied(num: pd.Series, street: pd.Series, mail: pd.Series) -> pd.Series:
    """Mailing address contains the property's house number and first street word."""

    def up(s: pd.Series) -> pd.Series:
        return s.fillna("").astype(str).str.upper().str.strip()

    num, mail = up(num), up(mail)
    first = up(street).str.split().str[0].fillna("")
    return pd.Series(
        [
            bool(n and s) and re.search(rf"\b{re.escape(n)}\b", m) is not None and s in m
            for n, s, m in zip(num, first, mail, strict=True)
        ],
        index=mail.index,
    )


def _street(df: pd.DataFrame) -> pd.Series:
    parts = df[["situs_num", "situs_street_prefx", "situs_street", "situs_street_suffix"]]
    return parts.fillna("").astype(str).agg(" ".join, axis=1).str.split().str.join(" ")


def parse(paths: list[Path]) -> pd.DataFrame:
    rows = [f["attributes"] for p in paths for f in json.loads(p.read_text())]
    df = pd.DataFrame(rows, columns=FIELDS)
    df = df[df["PROP_ID"].notna()]
    year = pd.to_numeric(df["F1year_imprv"], errors="coerce")
    out = pd.DataFrame(
        {
            "county": "travis",
            "account": df["PROP_ID"].astype("int64").astype(str),
            "situs_address": _street(df).replace("", None),
            "situs_city": df["situs_city"].str.strip().str.upper(),
            "situs_zip": df["situs_zip"].map(zip5),
            "owner_name": df["py_owner_name"].str.strip(),
            "mail_address": df["py_address"].str.strip(),
            "state_class": df["land_state_cd"].str.strip(),
            "is_single_family": df["land_state_cd"].str.strip() == "A1",
            "homestead": owner_occupied(df["situs_num"], df["situs_street"], df["py_address"]),
            "confidential": df["py_owner_name"].fillna("").str.contains("CONFIDENTIAL", case=False),
            "market_value": pd.to_numeric(df["market_value"], errors="coerce"),
            "heated_sqft": None,
            "year_built": year.where(year > 1800).astype("Int64"),
            "has_solar": False,
            "has_pool": False,
            "bedrooms": None,
            "full_baths": None,
            "half_baths": None,
            "stories": None,
        }
    )
    return out[PROPERTY_COLUMNS].reset_index(drop=True)
