"""Step 1: pull permits from city open data and normalize to one schema.

Output: data/interim/permits_all.parquet  (one row per permit, candidates + recall sample)

Cities:
  - Austin      Socrata 3syk-w9eu (server-side keyword filter, has lat/lon, status, contractor)
  - San Antonio CKAN bulk CSVs (2020-2024 file + current file; coords in lon/lat or TX State Plane ft)
Fort Worth moved to ArcGIS Hub and Dallas' Socrata feed stops in 2020 -> not wired yet.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd
import requests
from pyproj import Transformer

from permits.keywords import AUSTIN_LIKE_TERMS, keyword_flags

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"

AUSTIN_URL = "https://data.austintexas.gov/resource/3syk-w9eu.json"
SA_BASE = "https://data.sanantonio.gov/dataset/05012dcb-ba1b-4ade-b5f3-7403bc7f52eb/resource"
SA_FILES = {
    "sa_2020_2024.csv": f"{SA_BASE}/c22b1ef2-dcf8-4d77-be1a-ee3638092aab/download/permits_issued_ending_12312024.csv",
    "sa_current.csv": f"{SA_BASE}/c21106f9-3ef5-4f3a-8604-f992b4db7512/download/permits_issued.csv",
}

COLUMNS = [
    "city", "permit_id", "permit_type", "work_class", "description", "address", "zip",
    "lat", "lon", "applied_date", "issued_date", "status", "valuation", "contractor",
    "class_hint", "source_row_kind",
]


# ---------------------------------------------------------------- Austin
def _soql_like_any(field: str, terms: list[str]) -> str:
    return " OR ".join(f"upper({field}) like '{t}'" for t in terms)


def _austin_pages(where: str, page: int = 50_000, max_rows: int | None = None):
    offset = 0
    while True:
        params = {"$where": where, "$limit": page, "$offset": offset, "$order": "permit_number"}
        r = requests.get(AUSTIN_URL, params=params, timeout=300)
        r.raise_for_status()
        rows = r.json()
        if not rows:
            return
        yield from rows
        offset += len(rows)
        if len(rows) < page or (max_rows and offset >= max_rows):
            return


def _austin_frame(rows: list[dict], kind: str) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    get = lambda c: df[c] if c in df else pd.Series([None] * len(df))
    return pd.DataFrame({
        "city": "austin",
        "permit_id": get("permit_number"),
        "permit_type": get("permit_type_desc"),
        "work_class": get("work_class"),
        "description": get("description"),
        "address": get("permit_location").fillna(get("original_address1")),
        "zip": get("original_zip"),
        "lat": pd.to_numeric(get("latitude"), errors="coerce"),
        "lon": pd.to_numeric(get("longitude"), errors="coerce"),
        "applied_date": pd.to_datetime(get("applieddate"), errors="coerce"),
        "issued_date": pd.to_datetime(get("issue_date"), errors="coerce"),
        "status": get("status_current"),
        "valuation": pd.to_numeric(get("total_job_valuation"), errors="coerce"),
        "contractor": get("contractor_company_name"),
        "class_hint": get("permit_class_mapped"),  # Residential / Commercial
        "source_row_kind": kind,
    })


def fetch_austin(since: str, recall_n: int) -> pd.DataFrame:
    date = f"applieddate >= '{since}T00:00:00'"
    kw = _soql_like_any("description", AUSTIN_LIKE_TERMS)
    ctr = _soql_like_any("contractor_company_name", ["%BASE POWER%", "%TESLA%", "%GENERAC%", "%SUNRUN%"])
    cand = list(_austin_pages(f"{date} AND (({kw}) OR ({ctr}))"))
    print(f"austin: {len(cand):,} keyword/contractor candidates")
    frames = [_austin_frame(cand, "candidate")]

    if recall_n:
        # Residential electrical permits that did NOT hit a keyword: measures prefilter recall.
        rec = list(_austin_pages(
            f"{date} AND permittype = 'EP' AND permit_class_mapped = 'Residential' AND NOT ({kw})",
            page=recall_n * 20, max_rows=recall_n * 20,
        ))
        rec = pd.DataFrame(rec).sample(min(recall_n, len(rec)), random_state=0).to_dict("records")
        print(f"austin: {len(rec):,} recall-sample rows")
        frames.append(_austin_frame(rec, "recall_sample"))
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------- San Antonio
_stateplane = Transformer.from_crs("EPSG:2278", "EPSG:4326", always_xy=True)  # TX South Central, US ft


def _sa_coords(x: pd.Series, y: pd.Series) -> tuple[pd.Series, pd.Series]:
    x, y = pd.to_numeric(x, errors="coerce"), pd.to_numeric(y, errors="coerce")
    lon, lat = x.copy(), y.copy()
    sp = x.abs() > 1000  # state plane feet rather than degrees
    if sp.any():
        lon[sp], lat[sp] = _stateplane.transform(x[sp].values, y[sp].values)
    return lat, lon


def fetch_san_antonio(since: str, recall_n: int) -> pd.DataFrame:
    frames = []
    for name, url in SA_FILES.items():
        path = RAW / name
        if not path.exists() or path.stat().st_size < 10_000:
            print(f"downloading {name}")
            with requests.get(url, stream=True, timeout=600) as r:
                r.raise_for_status()
                path.write_bytes(r.content)
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig", na_values=["NULL", ""])
        frames.append(df)
    df = pd.concat(frames, ignore_index=True).drop_duplicates("PERMIT #", keep="last")
    lat, lon = _sa_coords(df["X_COORD"], df["Y_COORD"])
    zip_ = df["ADDRESS"].str.extract(r"(\d{5})\s*$")[0]
    out = pd.DataFrame({
        "city": "san_antonio",
        "permit_id": df["PERMIT #"],
        "permit_type": df["PERMIT TYPE"],
        "work_class": df["WORK TYPE"],
        "description": df["PROJECT NAME"],
        "address": df["ADDRESS"],
        "zip": zip_,
        "lat": lat,
        "lon": lon,
        "applied_date": pd.to_datetime(df["DATE SUBMITTED"], errors="coerce", format="mixed"),
        "issued_date": pd.to_datetime(df["DATE ISSUED"], errors="coerce", format="mixed"),
        "status": "Issued",  # SA only publishes issued permits
        "valuation": pd.to_numeric(df["DECLARED VALUATION"], errors="coerce"),
        "contractor": df["PRIMARY CONTACT"],
        "class_hint": None,
        "source_row_kind": "candidate",
    })
    out = out[out["applied_date"].fillna(out["issued_date"]) >= since]

    text = (out["description"].fillna("") + " " + out["permit_type"].fillna("") + " "
            + out["contractor"].fillna(""))
    hit = keyword_flags(text).any(axis=1)
    cand = out[hit]
    print(f"san_antonio: {len(cand):,} keyword candidates of {len(out):,} permits since {since}")
    rec = out[~hit & out["permit_type"].str.contains("Electric", case=False, na=False)]
    rec = rec.sample(min(recall_n, len(rec)), random_state=0).assign(source_row_kind="recall_sample")
    return pd.concat([cand, rec], ignore_index=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2016-01-01")
    ap.add_argument("--recall-sample", type=int, default=250, help="non-keyword permits per city sent to the LLM")
    ap.add_argument("--cities", default="austin,san_antonio")
    args = ap.parse_args()

    INTERIM.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    fetchers = {"austin": fetch_austin, "san_antonio": fetch_san_antonio}
    df = pd.concat([fetchers[c](args.since, args.recall_sample) for c in args.cities.split(",")],
                   ignore_index=True)[COLUMNS]
    df["description"] = df["description"].fillna("").map(lambda s: re.sub(r"\s+", " ", s).strip())
    df = df.drop_duplicates(["city", "permit_id"])
    flags = keyword_flags(df["description"] + " " + df["permit_type"].fillna("") + " " + df["contractor"].fillna(""))
    df = pd.concat([df.reset_index(drop=True), flags.reset_index(drop=True)], axis=1)
    # Austin's server-side LIKE is looser than the regex: keep a candidate only if the regex agrees.
    df = df[(df["source_row_kind"] == "recall_sample") | flags.any(axis=1).values]
    df.to_parquet(INTERIM / "permits_all.parquet", index=False)
    print(df.groupby(["city", "source_row_kind"]).size().to_string())
    print(flags.groupby(df["city"]).sum().to_string())


if __name__ == "__main__":
    main()
