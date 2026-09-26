"""Fetch ERCOT settlement point prices.

Two sources, both returning the same frame
(settlement_point, market, interval_start [UTC], price):

- Historical yearly files (public MIS downloads, no auth) for the bulk backfill:
  "Historical RTM Load Zone and Hub Prices" (report 13061) and
  "Historical DAM Load Zone and Hub Prices" (report 13060). ERCOT refreshes the
  current-year files roughly weekly.
- ERCOT Public API for the most recent days the yearly files don't cover yet.
"""

import io
import time
import zipfile
from datetime import date

import httpx
import pandas as pd

from app.config import settings
from app.grid.zones import TRACKED_POINTS

COLUMNS = ["settlement_point", "market", "interval_start", "price"]
ERCOT_TZ = "America/Chicago"
_UA = {"User-Agent": "base-power-gtm/0.1"}


def _to_utc(local: pd.Series, repeated: pd.Series) -> pd.Series:
    # ERCOT publishes local prevailing time; the repeated (second) hour on the DST
    # fall-back day is flagged, which is exactly pandas' "not DST" for ambiguous times.
    is_dst = ~repeated.astype(bool).to_numpy()
    return local.dt.tz_localize(ERCOT_TZ, ambiguous=is_dst).dt.tz_convert("UTC")


def _yes(s: pd.Series) -> pd.Series:
    return s.astype(str).str.upper().isin(["Y", "TRUE"])


# --- Historical yearly files -------------------------------------------------------

MIS_LIST = "https://www.ercot.com/misapp/servlets/IceDocListJsonWS?reportTypeId={}"
MIS_DOWNLOAD = "https://www.ercot.com/misdownload/servlets/mirDownload?doclookupId={}"
REPORTS = {"RT": (13061, "RTMLZHBSPP_{}"), "DA": (13060, "DAMLZHBSPP_{}")}


def fetch_historical_year(market: str, year: int) -> pd.DataFrame:
    report_id, name = REPORTS[market]
    docs = httpx.get(MIS_LIST.format(report_id), headers=_UA, timeout=60).json()
    doc_id = next(
        d["Document"]["DocID"]
        for d in docs["ListDocsByRptTypeRes"]["DocumentList"]
        if d["Document"]["FriendlyName"] == name.format(year)
    )
    resp = httpx.get(MIS_DOWNLOAD.format(doc_id), headers=_UA, timeout=300)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        xlsx = zf.read(zf.namelist()[0])

    sheets = pd.read_excel(io.BytesIO(xlsx), sheet_name=None)  # one sheet per month
    raw = pd.concat([s for s in sheets.values() if not s.empty], ignore_index=True)
    return parse_historical(market, raw)


def parse_historical(market: str, raw: pd.DataFrame) -> pd.DataFrame:
    point_col = "Settlement Point Name" if market == "RT" else "Settlement Point"
    raw = raw[raw[point_col].isin(TRACKED_POINTS)]
    day = pd.to_datetime(raw["Delivery Date"], format="%m/%d/%Y")
    if market == "RT":
        offset = pd.to_timedelta(raw["Delivery Hour"] - 1, unit="h") + pd.to_timedelta(
            (raw["Delivery Interval"] - 1) * 15, unit="min"
        )
    else:
        offset = pd.to_timedelta(raw["Hour Ending"].str[:2].astype(int) - 1, unit="h")
    return pd.DataFrame(
        {
            "settlement_point": raw[point_col],
            "market": market,
            "interval_start": _to_utc(day + offset, _yes(raw["Repeated Hour Flag"])),
            "price": raw["Settlement Point Price"].astype(float),
        }
    )[COLUMNS]


# --- Live MIS reports (public, no login) ------------------------------------------------
# NP6-905-CD real-time settlement point prices (every 15 min) and NP4-190-CD day-ahead
# settlement point prices (daily, for the next day). Used by the Need Engine's live grid
# signals; rows land in grid_prices, so zone economics stay current without API creds.

MIS_LIVE = {"RT": 12301, "DA": 12331}


def parse_mis_prices(market: str, csv_text: str) -> pd.DataFrame:
    raw = pd.read_csv(io.StringIO(csv_text), skipinitialspace=True)
    point_col = "SettlementPointName" if market == "RT" else "SettlementPoint"
    raw = raw[raw[point_col].isin(TRACKED_POINTS)]
    if market == "RT":  # load zones also appear energy-weighted (LZEW): keep the plain series
        raw = raw[~raw["SettlementPointType"].astype(str).str.endswith("EW")]
    day = pd.to_datetime(raw["DeliveryDate"], format="%m/%d/%Y")
    if market == "RT":
        offset = pd.to_timedelta(raw["DeliveryHour"] - 1, unit="h") + pd.to_timedelta(
            (raw["DeliveryInterval"] - 1) * 15, unit="min"
        )
    else:
        offset = pd.to_timedelta(raw["HourEnding"].str[:2].astype(int) - 1, unit="h")
    return pd.DataFrame(
        {
            "settlement_point": raw[point_col],
            "market": market,
            "interval_start": _to_utc(day + offset, _yes(raw["DSTFlag"])),
            "price": raw["SettlementPointPrice"].astype(float),
        }
    )[COLUMNS]


def fetch_mis_recent(market: str, documents: int) -> pd.DataFrame:
    """The latest `documents` CSV publications of a live MIS price report."""
    listing = httpx.get(MIS_LIST.format(MIS_LIVE[market]), headers=_UA, timeout=60)
    docs = sorted(
        (
            d["Document"]
            for d in listing.raise_for_status().json()["ListDocsByRptTypeRes"]["DocumentList"]
            if d["Document"]["FriendlyName"].endswith("_csv")
        ),
        key=lambda d: d["PublishDate"],
        reverse=True,
    )[:documents]
    frames = []
    for doc in docs:
        resp = httpx.get(MIS_DOWNLOAD.format(doc["DocID"]), headers=_UA, timeout=120)
        with zipfile.ZipFile(io.BytesIO(resp.raise_for_status().content)) as zf:
            frames.append(parse_mis_prices(market, zf.read(zf.namelist()[0]).decode()))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)


# --- ERCOT Public API ----------------------------------------------------------------

API_BASE = "https://api.ercot.com/api/public-reports"
TOKEN_URL = (
    "https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com/"
    "B2C_1_PUBAPI-ROPC-FLOW/oauth2/v2.0/token"
)
CLIENT_ID = "fec253ea-0d06-4272-a5e6-b478baeecd70"  # ERCOT's fixed public client id
ENDPOINTS = {"RT": "np6-905-cd/spp_node_zone_hub", "DA": "np4-190-cd/dam_stlmnt_pnt_prices"}


class ErcotApi:
    def __init__(self) -> None:
        missing = [
            name
            for name in ("ercot_username", "ercot_password", "ercot_primary_key")
            if not getattr(settings, name)
        ]
        if missing:
            env = ", ".join(m.upper() for m in missing)
            raise RuntimeError(f"ERCOT API needs {env} in .env")
        self.keys = [k for k in (settings.ercot_primary_key, settings.ercot_secondary_key) if k]
        self.client = httpx.Client(base_url=API_BASE, headers=_UA, timeout=120)
        self.token = self._token()

    def _token(self) -> str:
        resp = httpx.post(
            TOKEN_URL,
            data={
                "grant_type": "password",
                "username": settings.ercot_username,
                "password": settings.ercot_password,
                "response_type": "id_token",
                "scope": f"openid {CLIENT_ID} offline_access",
                "client_id": CLIENT_ID,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["id_token"]

    def _get(self, path: str, params: dict) -> dict:
        # Try the primary subscription key, then the secondary if it's rejected or throttled.
        for key in self.keys:
            resp = self.client.get(
                path,
                params=params,
                headers={"Authorization": f"Bearer {self.token}", "Ocp-Apim-Subscription-Key": key},
            )
            if resp.status_code not in (401, 403, 429):
                break
        resp.raise_for_status()
        return resp.json()

    def fetch(self, market: str, start: date, end: date) -> pd.DataFrame:
        rows: list[dict] = []
        for point in TRACKED_POINTS:
            page = 1
            while True:
                body = self._get(
                    ENDPOINTS[market],
                    {
                        "settlementPoint": point,
                        "deliveryDateFrom": start.isoformat(),
                        "deliveryDateTo": end.isoformat(),
                        "size": 10_000,
                        "page": page,
                    },
                )
                names = [f["name"] for f in body["fields"]]
                rows += [dict(zip(names, r, strict=True)) for r in body["data"]]
                if page >= body["_meta"]["totalPages"]:
                    break
                page += 1
            time.sleep(2)  # stay well under the API rate limit
        return parse_api(market, pd.DataFrame(rows))

    def close(self) -> None:
        self.client.close()


def parse_api(market: str, raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=COLUMNS)
    day = pd.to_datetime(raw["deliveryDate"])
    if market == "RT":
        offset = pd.to_timedelta(raw["deliveryHour"] - 1, unit="h") + pd.to_timedelta(
            (raw["deliveryInterval"] - 1) * 15, unit="min"
        )
    else:
        offset = pd.to_timedelta(raw["hourEnding"].str[:2].astype(int) - 1, unit="h")
    return pd.DataFrame(
        {
            "settlement_point": raw["settlementPoint"],
            "market": market,
            "interval_start": _to_utc(day + offset, _yes(raw["DSTFlag"])),
            "price": raw["settlementPointPrice"].astype(float),
        }
    )[COLUMNS]
