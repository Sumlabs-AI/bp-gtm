"""Fetch CenterPoint and Oncor service points from ERCOT MIS TDSP ESI ID Extract (report 203).

ERCOT publishes a monthly full ZIP and daily change ZIPs. Each contains a
headerless, 22-column CSV described by the TDSP ESI ID Extract layout.
"""

from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

import httpx
import pandas as pd

from app.leads.frames import METER_COLUMNS

SOURCE_ID: str = "ercot_tdsp_esiid_extract"

_MIS_LIST = "https://www.ercot.com/misapp/servlets/IceDocListJsonWS?reportTypeId=203"
_MIS_DOWNLOAD = "https://www.ercot.com/misdownload/servlets/mirDownload?doclookupId={}"
_HEADERS = {"User-Agent": "base-power-gtm/0.1"}

# Listing name prefix (padded with "_", then FUL/DAILY) -> (DUNS in the CSV, canonical TDSP name).
# Oncor serves most of Travis outside Austin Energy (e.g. Pflugerville, Manor).
_TDSPS = {
    "CENTERPOINT__": ("957877905", "centerpoint"),
    "ONCOR_ELEC___": ("1039940674000", "oncor"),
}
_CSV_COLUMNS = [0, 1, 2, 3, 5, 6, 7, 9, 10]


def _documents() -> list[dict[str, str]]:
    response = httpx.get(_MIS_LIST, headers=_HEADERS, timeout=60)
    response.raise_for_status()
    names = {f"{prefix}{kind}" for prefix in _TDSPS for kind in ("FUL", "DAILY")}
    return [
        item["Document"]
        for item in response.json()["ListDocsByRptTypeRes"]["DocumentList"]
        if item["Document"]["FriendlyName"] in names
    ]


def _document_key(document: dict[str, str]) -> tuple[datetime, int]:
    return datetime.fromisoformat(document["PublishDate"]), int(document["DocID"])


def _current_documents() -> list[dict[str, str]]:
    documents = _documents()
    selected = []
    for prefix in _TDSPS:
        fulls = [d for d in documents if d["FriendlyName"] == f"{prefix}FUL"]
        if not fulls:
            raise ValueError(f"No current {prefix} monthly full file in ERCOT MIS")
        full = max(fulls, key=_document_key)
        daily = [
            d
            for d in documents
            if d["FriendlyName"] == f"{prefix}DAILY"
            and _document_key(d)[0] > _document_key(full)[0]
        ]
        selected.extend([full, *daily])
    return sorted(selected, key=_document_key)


def fingerprint() -> str:
    """Return the DocIDs in the current full-plus-daily snapshot of every TDSP."""
    return ",".join(document["DocID"] for document in _current_documents())


def fetch(raw_dir: Path) -> list[Path]:
    """Save the latest monthly full and all later daily ZIPs, with document metadata."""
    paths = []
    with httpx.Client(headers=_HEADERS, timeout=300) as client:
        for document in _current_documents():
            published = datetime.fromisoformat(document["PublishDate"])
            stamp = published.strftime("%Y%m%dT%H%M%S%z")
            path = raw_dir / f"{document['DocID']}_{stamp}_{document['FriendlyName']}.zip"
            if not path.exists():
                partial = path.with_suffix(".zip.part")
                try:
                    with client.stream("GET", _MIS_DOWNLOAD.format(document["DocID"])) as response:
                        response.raise_for_status()
                        with partial.open("wb") as file:
                            for block in response.iter_bytes():
                                file.write(block)
                    partial.replace(path)
                finally:
                    partial.unlink(missing_ok=True)
            paths.append(path)
    return paths


def _snake_case(values: pd.Series) -> pd.Series:
    # PREMISE_TYPE: Residential -> residential; Small Non-Residential ->
    # small_non_residential; Large Non-Residential -> large_non_residential.
    # STATUS: Active -> active; Inactive -> inactive; De-Energized -> de_energized.
    normalized = (
        values.str.strip().str.lower().str.replace(r"[^a-z0-9]+", "_", regex=True).str.strip("_")
    )
    return normalized.mask(normalized.eq(""))


def _clean_chunk(raw: pd.DataFrame, published: pd.Timestamp) -> pd.DataFrame:
    duns_to_name = {duns: name for duns, name in _TDSPS.values()}
    raw = raw[raw[7].isin(duns_to_name) & raw[0].ne("")]
    address = (raw[1] + " " + raw[2]).str.replace(r"\s+", " ", regex=True).str.strip()
    city = raw[3].str.strip()
    county = raw[6].str.strip().str.lower()
    return pd.DataFrame(
        {
            "esiid": raw[0].str.strip(),
            "tdsp": raw[7].map(duns_to_name),
            "address": address.mask(address.eq("")),
            "city": city.mask(city.eq("")),
            "zip": raw[5].str.strip().str.extract(r"^(\d{5})", expand=False),
            "county": county.mask(county.eq("")),
            "premise_type": _snake_case(raw[10]),
            "status": _snake_case(raw[9]),
            "published_at": published,
        }
    )


def parse(paths: list[Path]) -> pd.DataFrame:
    """Parse ZIPs in publish order and keep the latest record for each ESI ID."""
    frames = []
    for path in sorted(paths, key=lambda p: _document_key_from_path(p)):
        published = pd.Timestamp(_document_key_from_path(path)[0]).tz_convert("UTC")
        with ZipFile(path) as archive:
            members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if not members:
                raise ValueError(f"No CSV found in {path}")
            for member in members:
                with archive.open(member) as file:
                    for chunk in pd.read_csv(
                        file,
                        header=None,
                        usecols=_CSV_COLUMNS,
                        dtype=str,
                        encoding="utf-8",
                        na_filter=False,
                        chunksize=100_000,
                    ):
                        frames.append(_clean_chunk(chunk, published))
    if not frames:
        return pd.DataFrame(columns=METER_COLUMNS)
    return (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates("esiid", keep="last")
        .reset_index(drop=True)[METER_COLUMNS]
    )


def _document_key_from_path(path: Path) -> tuple[datetime, int]:
    doc_id, stamp, _ = path.stem.split("_", 2)
    return datetime.strptime(stamp, "%Y%m%dT%H%M%S%z"), int(doc_id)
