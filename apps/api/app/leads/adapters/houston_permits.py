"""City of Houston weekly sold-permit reports.

The report page lists one workbook per week. Most are .xlsx. A few weeks are
.xls files that are actually HTML tables with the same columns. Links for the
newest weeks are sometimes wrapped in an Office viewer URL; the workbook URL is
the src query parameter.

Each workbook has a short preamble (report title, sometimes From/To), a header
row (Zip Code, Permit Date, Permit Type, Project No, Address, Comments), then a
disclaimer footer. Category comes from Permit Type plus Comments. There is no
geometry. parse() keeps solar, EV charger, and new single-family rows only.
"""

import hashlib
import re
import time
from datetime import date, datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
import pandas as pd

from app.leads.adapters.permit_categories import classify
from app.leads.frames import PERMIT_CATEGORIES, PERMIT_COLUMNS

SOURCE_ID = "houston_weekly_sold_permits"
PAGE_URL = "https://www.houstonpermittingcenter.org/sold-permits-search"
_UA = {"User-Agent": "base-power-gtm/0.1"}
_TIMEOUT = 120
_DELAY_S = 0.5
_KEEP = PERMIT_CATEGORIES - {"other"}
_COLUMNS = {
    "zip code": "zip",
    "permit date": "issued",
    "permit type": "permit_type",
    "project no": "permit_id",
    "address": "address",
    "comments": "comments",
}


def fingerprint() -> str:
    """SHA-256 of the sorted weekly workbook URLs currently linked on the page."""
    urls = _spreadsheet_urls(_get_text(PAGE_URL))
    return hashlib.sha256("\n".join(urls).encode()).hexdigest()


def fetch(raw_dir: Path) -> list[Path]:
    """Download every weekly workbook linked from the report page."""
    urls = _spreadsheet_urls(_get_text(PAGE_URL))
    paths: list[Path] = []
    used: set[str] = set()
    for index, url in enumerate(urls):
        if index:
            time.sleep(_DELAY_S)
        resp = httpx.get(url, headers=_UA, timeout=_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        path = raw_dir / _filename(url, used)
        path.write_bytes(resp.content)
        paths.append(path)
    return paths


def parse(paths: list[Path]) -> pd.DataFrame:
    """Parse downloaded weekly workbooks into the permit frame. No network."""
    records: list[dict] = []
    for path in paths:
        for row in _data_rows(_table(path)):
            kept = _row(row)
            if kept is not None:
                records.append(kept)
    return _frame(records)


def _spreadsheet_urls(html: str) -> list[str]:
    found: set[str] = set()
    for href in re.findall(r"""href=["']([^"']+)["']""", html):
        url = _unwrap(href)
        if url is None:
            continue
        path = urlparse(url).path.lower()
        if path.endswith(".xlsx") or path.endswith(".xls"):
            found.add(url)
    return sorted(found)


def _unwrap(href: str) -> str | None:
    href = unescape(href)
    if "officeapps.live.com" in href:
        src = parse_qs(urlparse(href).query).get("src")
        if not src:
            return None
        href = src[0]
    return urljoin(PAGE_URL, href)


def _get_text(url: str) -> str:
    resp = httpx.get(url, headers=_UA, timeout=_TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def _filename(url: str, used: set[str]) -> str:
    base = unquote(Path(urlparse(url).path).name)
    base = re.sub(r"[^\w. -]+", "_", base).strip() or "weekly.xlsx"
    stem, suffix = Path(base).stem, Path(base).suffix
    name = base
    number = 2
    while name in used:
        name = f"{stem}_{number}{suffix}"
        number += 1
    used.add(name)
    return name


def _table(path: Path) -> list[list]:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        return _excel_rows(path)
    if suffix == ".xls":
        raw = path.read_bytes()
        if raw[:2] == b"PK":
            return _excel_rows(path)
        if raw.lstrip()[:1] == b"<":
            return _html_rows(raw)
        raise ValueError(f"{path.name} is a binary .xls file, not the HTML export")
    raise ValueError(f"unsupported permit workbook {path.name}")


def _excel_rows(path: Path) -> list[list]:
    frame = pd.read_excel(path, header=None, dtype=object)
    frame = frame.where(frame.notna(), None)
    return frame.values.tolist()


def _html_rows(raw: bytes) -> list[list]:
    encoding = "windows-1252" if b"windows-1252" in raw[:500].lower() else "utf-8"
    parser = _HtmlTable()
    parser.feed(raw.decode(encoding, errors="replace"))
    return parser.rows


class _HtmlTable(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] = []
        self._cell: list[str] = []
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._cell = []
        elif tag == "br" and self._in_cell:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._in_cell:
            text = re.sub(r"\s+", " ", "".join(self._cell).replace("\xa0", " ")).strip()
            self._row.append(text)
            self._in_cell = False
        elif tag == "tr":
            if any(self._row):
                self.rows.append(self._row)
            self._row = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)


def _data_rows(rows: list[list]) -> list[dict]:
    header_at = None
    indexes: dict[str, int] = {}
    for index, row in enumerate(rows):
        cells = [_clean(cell) or "" for cell in row]
        if cells and cells[0].casefold() == "zip code":
            header_at = index
            for col, name in enumerate(cells):
                key = _COLUMNS.get(name.casefold())
                if key is not None:
                    indexes[key] = col
            break
    if header_at is None or "permit_id" not in indexes:
        raise ValueError("weekly permit workbook is missing the Zip Code header")
    parsed: list[dict] = []
    for row in rows[header_at + 1 :]:
        record = {key: _at(row, col) for key, col in indexes.items()}
        # The disclaimer footer mentions a phone number, so a zip has to be the whole cell.
        if _zip_cell(record.get("zip")) or _project_id(record.get("permit_id")):
            parsed.append(record)
    return parsed


def _row(record: dict) -> dict | None:
    description = _join(record.get("permit_type"), record.get("comments"))
    category = classify(description)
    if category not in _KEEP:
        return None
    address = _clean(record.get("address"))
    if address:
        address = re.sub(r"\s+", " ", address)
    return {
        "source": SOURCE_ID,
        "permit_id": _project_id(record.get("permit_id")),
        "address": address,
        "city": "Houston",
        "zip": _zip_cell(record.get("zip")),
        "issued_date": _issued(record.get("issued")),
        "category": category,
        "description": description,
        "lat": None,
        "lon": None,
    }


def _zip_cell(value: object) -> str | None:
    text = _clean(value)
    if text is None:
        return None
    match = re.fullmatch(r"(\d{5})(?:-\d{4})?", text)
    return match.group(1) if match else None


def _project_id(value: object) -> str | None:
    text = _clean(value)
    if text is None:
        return None
    # Excel stores Project No as a number; don't keep a trailing ".0".
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _issued(value: object) -> date | None:
    if value is None or _missing(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    parsed = pd.to_datetime(text, format="%Y/%m/%d", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _at(row: list, index: int) -> object:
    if index >= len(row):
        return None
    return row[index]


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
    return bool(isinstance(value, float) and pd.isna(value))


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
