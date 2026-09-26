"""Offline checks using seven anonymized rows trimmed from HCAD's 2026 ZIPs."""

from collections.abc import Callable
from pathlib import Path

import httpx
import pandas as pd
import pytest

from app.leads.adapters import hcad
from app.leads.frames import PROPERTY_COLUMNS

_FIXTURES = Path(__file__).parent / "fixtures" / "leads" / "hcad"
_ARCHIVES = ["Real_acct_owner.zip", "Real_building_land.zip", "Real_jur_exempt.zip"]


def _mock_http(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    real_client = httpx.Client

    def client(**kwargs: object) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(hcad.httpx, "Client", client)


def test_parse_real_zip_samples() -> None:
    frame = hcad.parse([_FIXTURES / name for name in reversed(_ARCHIVES)])
    assert hcad.SOURCE_ID == "hcad_harris_cama_2026"
    assert frame.columns.tolist() == PROPERTY_COLUMNS
    assert len(frame) == 7
    assert frame["account"].is_unique
    assert frame["account"].str.len().eq(13).all()
    assert frame["county"].eq("harris").all()

    rows = frame.set_index("account")
    commercial = rows.loc["0000000000001"]
    assert commercial["situs_address"] == "1 SAMPLE ST"
    assert commercial["situs_city"] == "TEST CITY"
    assert commercial["situs_zip"] == "00001"
    assert commercial["mail_address"] == "1 FAKE ST, FAKETOWN, TX 00001-0000"
    assert commercial["market_value"] == 310165.0
    assert not commercial["is_single_family"]
    assert pd.isna(commercial["heated_sqft"])
    assert pd.isna(commercial["year_built"])

    residential = rows.loc["0000000000002"]
    assert residential["has_solar"] and residential["has_pool"]  # RSP1 + RRP9
    assert rows.loc["0000000000003", "has_pool"] and not rows.loc["0000000000003", "has_solar"]
    assert not rows.loc["0000000000005", "has_pool"]  # CSC1 is a commercial pool
    assert residential["is_single_family"]
    assert residential["homestead"]  # RES
    assert residential["heated_sqft"] == 2328.0
    assert residential["year_built"] == 2014

    largest_second = rows.loc["0000000000003"]
    assert largest_second["heated_sqft"] == 1500.0  # building 2 exceeds building 1
    assert largest_second["year_built"] == 1950
    assert not largest_second["homestead"]

    current_owner = rows.loc["0000000000004"]
    assert current_owner["homestead"]  # RES SOL is a space-separated code list
    assert current_owner["confidential"]
    assert current_owner["owner_name"] is None
    assert current_owner["mail_address"] is None

    partial = rows.loc["0000000000005"]
    assert partial["homestead"]  # PAR
    assert partial["mail_address"] == "5 FAKE ST, UNIT 9, FAKETOWN, TX 00005-0000"

    assert not rows.loc["0000000000006", "homestead"]  # FIR is not current homestead
    confidential = rows.loc["0000000000007"]
    assert confidential["confidential"]  # explicit CONFIDENTIAL label
    assert confidential["owner_name"] is None
    assert confidential["mail_address"] is None
    assert not confidential["homestead"]  # V14 is not a homestead code


def test_fingerprint_uses_only_head_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []
    etags = {name: f'"{index}"' for index, name in enumerate(_ARCHIVES)}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        name = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(
            200,
            headers={
                "Last-Modified": "Sun, 20 Sep 2026 21:25:00 GMT",
                "ETag": etags[name],
                "Content-Length": "123",
            },
        )

    _mock_http(monkeypatch, handler)
    first = hcad.fingerprint()
    assert hcad.fingerprint() == first
    etags[_ARCHIVES[1]] = '"changed"'
    assert hcad.fingerprint() != first
    # Per call: one HEAD to find the tax-year folder, then one per archive.
    assert [request.method for request in requests] == ["HEAD"] * 12
    assert [request.url.path.rsplit("/", 1)[-1] for request in requests[1:4]] == _ARCHIVES


def test_fetch_keeps_original_zip_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        name = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, content=(_FIXTURES / name).read_bytes())

    _mock_http(monkeypatch, handler)
    paths = hcad.fetch(tmp_path)
    assert [path.name for path in paths] == _ARCHIVES
    assert [request.method for request in requests] == ["HEAD", "GET", "GET", "GET"]
    for path in paths:
        assert path.read_bytes() == (_FIXTURES / path.name).read_bytes()
    assert len(hcad.parse(paths)) == 7
