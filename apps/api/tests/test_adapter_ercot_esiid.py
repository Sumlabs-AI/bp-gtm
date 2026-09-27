"""Offline tests using trimmed, anonymized ERCOT CenterPoint ZIPs."""

import io
import zipfile
from pathlib import Path

import httpx
import pandas as pd

from app.leads.adapters import ercot_esiid
from app.leads.frames import METER_COLUMNS

FIXTURES = Path(__file__).parent / "fixtures/leads/ercot_esiid"
FULL = FIXTURES / "1271779092_20260907T181158-0500_CENTERPOINT__FUL.zip"
DAILY = FIXTURES / "1278757464_20260925T055832-0500_CENTERPOINT__DAILY.zip"


def _document(doc_id: str, published: str, name: str) -> dict[str, str]:
    return {"DocID": doc_id, "PublishDate": published, "FriendlyName": name}


def test_parse_real_centerpoint_zip_format() -> None:
    frame = ercot_esiid.parse([DAILY, FULL])

    assert list(frame.columns) == METER_COLUMNS
    assert len(frame) == 6
    assert frame["esiid"].is_unique
    assert set(frame["tdsp"]) == {"centerpoint"}
    rows = frame.set_index("esiid")

    updated = rows.loc["9990000000000000000001"]
    assert updated["address"] == "11 FAKE ST"
    assert updated["zip"] == "77004"
    assert updated["county"] == "harris"
    assert updated["premise_type"] == "residential"
    assert updated["status"] == "active"
    assert updated["published_at"] == pd.Timestamp("2026-09-25T10:58:32Z")

    overflow = rows.loc["9990000000000000000002"]
    assert overflow["address"] == "4 FAKE ST"
    assert overflow["premise_type"] == "small_non_residential"
    assert overflow["status"] == "de_energized"
    assert overflow["published_at"] == pd.Timestamp("2026-09-07T23:11:58Z")

    assert rows.loc["9990000000000000000003", "premise_type"] == "large_non_residential"
    assert pd.isna(rows.loc["9990000000000000000003", "county"])
    assert pd.isna(rows.loc["9990000000000000000004", "premise_type"])
    assert rows.loc["9990000000000000000006", "status"] == "inactive"
    assert isinstance(frame["published_at"].dtype, pd.DatetimeTZDtype)


def test_fingerprint_uses_current_full_and_every_later_daily(monkeypatch) -> None:
    documents = [
        _document("5", "2026-09-25T05:58:32-05:00", "CENTERPOINT__DAILY"),
        _document("2", "2026-09-06T05:39:54-05:00", "CENTERPOINT__DAILY"),
        _document("3", "2026-09-07T18:11:58-05:00", "CENTERPOINT__FUL"),
        _document("4", "2026-09-24T05:47:40-05:00", "CENTERPOINT__DAILY"),
        _document("1", "2026-08-04T18:11:58-05:00", "CENTERPOINT__FUL"),
        _document("6", "2026-09-25T05:58:32-05:00", "ONCOR_ELEC___DAILY"),
        _document("7", "2026-09-07T18:11:39-05:00", "ONCOR_ELEC___FUL"),
        _document("8", "2026-09-07T18:11:39-05:00", "AEP_NORTH____FUL"),
    ]

    def listing(url: str, **kwargs) -> httpx.Response:
        assert url == ercot_esiid._MIS_LIST
        assert kwargs["headers"] == ercot_esiid._HEADERS
        return httpx.Response(
            200,
            json={
                "ListDocsByRptTypeRes": {
                    "DocumentList": [{"Document": document} for document in documents]
                }
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(ercot_esiid.httpx, "get", listing)
    assert ercot_esiid.fingerprint() == "7,3,4,5,6"


def test_fetch_saves_metadata_and_reuses_downloads(monkeypatch, tmp_path: Path) -> None:
    documents = [
        _document("1271779092", "2026-09-07T18:11:58-05:00", "CENTERPOINT__FUL"),
        _document("1278757464", "2026-09-25T05:58:32-05:00", "CENTERPOINT__DAILY"),
    ]
    payloads = {"1271779092": FULL.read_bytes(), "1278757464": DAILY.read_bytes()}
    requested: list[str] = []
    client_class = httpx.Client

    def respond(request: httpx.Request) -> httpx.Response:
        doc_id = request.url.params["doclookupId"]
        requested.append(doc_id)
        return httpx.Response(200, content=payloads[doc_id])

    monkeypatch.setattr(ercot_esiid, "_current_documents", lambda: documents)
    monkeypatch.setattr(
        ercot_esiid.httpx,
        "Client",
        lambda **kwargs: client_class(transport=httpx.MockTransport(respond), **kwargs),
    )

    paths = ercot_esiid.fetch(tmp_path)
    assert [path.name for path in paths] == [FULL.name, DAILY.name]
    assert [path.read_bytes() for path in paths] == [FULL.read_bytes(), DAILY.read_bytes()]
    assert requested == ["1271779092", "1278757464"]
    assert ercot_esiid.fetch(tmp_path) == paths
    assert requested == ["1271779092", "1278757464"]


def test_parse_keeps_oncor_and_drops_other_tdsps(tmp_path: Path) -> None:
    rows = (
        '"9990000000000000000101","01718     OAK                         ST",,"PFLUGERVILLE",'
        '"TX","786601234","TRAVIS","1039940674000","13","Active","Residential"\n'
        '"9990000000000000000102","5 FAKE ST",,"ABILENE","TX","79601","TAYLOR","007923311",'
        '"13","Active","Residential"\n'
    )
    path = tmp_path / "7_20260907T181139-0500_ONCOR_ELEC___FUL.zip"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("oncor.csv", rows)
    path.write_bytes(buffer.getvalue())

    frame = ercot_esiid.parse([path])
    assert frame["esiid"].tolist() == ["9990000000000000000101"]
    assert frame.loc[0, "tdsp"] == "oncor"
    assert frame.loc[0, "county"] == "travis"
