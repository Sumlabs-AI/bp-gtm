"""City of Austin issued construction permits (Socrata 3syk-w9eu, no key needed).

A server-side keyword filter narrows residential permits issued in the last LOOKBACK_DAYS to
solar / EV / new-home candidates; permit_categories.classify() then decides. Rows have
coordinates and the street address in `permit_location` / `original_address1`.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

from app.leads.adapters.permit_categories import classify
from app.leads.address import zip5
from app.leads.frames import PERMIT_CATEGORIES, PERMIT_COLUMNS

SOURCE_ID = "austin_permits"
URL = "https://data.austintexas.gov/resource/3syk-w9eu.json"
LOOKBACK_DAYS = 3 * 365
PAGE = 50_000
TERMS = [
    "%SOLAR%",
    "%PHOTOVOLTAIC%",
    "%PV SYSTEM%",
    "%ELECTRIC VEHICLE%",
    "%EV CHARG%",
    "%EVSE%",
    "%VEHICLE CHARGING%",
    "%SINGLE FAMILY%",
    "%1 FAMILY%",
    "%ONE FAMILY%",
]
_KEEP = PERMIT_CATEGORIES - {"other"}
_UA = {"User-Agent": "base-power-gtm/0.1"}


def _where() -> str:
    since = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    like = " OR ".join(f"upper(description) like '{t}'" for t in TERMS)
    return f"issue_date >= '{since}T00:00:00' AND permit_class_mapped = 'Residential' AND ({like})"


def fingerprint() -> str:
    """Newest issue date and row count of the candidate set."""
    params = {"$select": "count(*) AS n, max(issue_date) AS latest", "$where": _where()}
    resp = httpx.get(URL, params=params, headers=_UA, timeout=120)
    resp.raise_for_status()
    row = resp.json()[0]
    return f"{row.get('n')}:{row.get('latest')}"


def fetch(raw_dir: Path) -> list[Path]:
    paths, offset = [], 0
    with httpx.Client(headers=_UA, timeout=300) as client:
        while True:
            params = {
                "$where": _where(),
                "$limit": PAGE,
                "$offset": offset,
                "$order": "permit_number",
            }
            rows = client.get(URL, params=params).raise_for_status().json()
            if not rows:
                break
            path = raw_dir / f"page_{len(paths):03d}.json"
            path.write_text(json.dumps(rows))
            paths.append(path)
            offset += len(rows)
            if len(rows) < PAGE:
                break
    return paths


def parse(paths: list[Path]) -> pd.DataFrame:
    df = pd.DataFrame([r for p in paths for r in json.loads(p.read_text())])
    if df.empty:
        return pd.DataFrame(columns=PERMIT_COLUMNS)

    def col(name: str) -> pd.Series:
        return df[name] if name in df else pd.Series(None, index=df.index, dtype=object)

    text = col("permit_type_desc").fillna("") + " " + col("description").fillna("")
    out = pd.DataFrame(
        {
            "source": SOURCE_ID,
            "permit_id": col("permit_number"),
            "address": col("original_address1").fillna(col("permit_location")),
            "city": col("original_city").str.upper(),
            "zip": col("original_zip").map(zip5),
            "issued_date": pd.to_datetime(col("issue_date"), errors="coerce").dt.date,
            "category": text.map(classify),
            "description": col("description"),
            "lat": pd.to_numeric(col("latitude"), errors="coerce"),
            "lon": pd.to_numeric(col("longitude"), errors="coerce"),
        }
    )
    out = out[out["category"].isin(_KEEP) & out["permit_id"].notna() & out["address"].notna()]
    return out[PERMIT_COLUMNS].reset_index(drop=True)
