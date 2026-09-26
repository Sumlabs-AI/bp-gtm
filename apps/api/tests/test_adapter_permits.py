"""Permit category rules and Harris / Houston adapter parses. No network."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app.leads.adapters import harris_permits, houston_permits
from app.leads.adapters.permit_categories import classify
from app.leads.frames import PERMIT_COLUMNS

FIXTURES = Path(__file__).parent / "fixtures" / "leads" / "permits"


def _cell(value: object) -> object:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return value


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Solar Photovoltaic Power System", "solar"),
        ("NEW RESIDENTIAL SOLAR PANELS 2021 IRC", "solar"),
        ("SF RESIDENTIAL SOLAR PANEL ADDITION 1-2-5-R3-B 2021 IRC", "solar"),
        ("OFFICE NEW ROOFTOP SOLAR PANELS 1-1-2-B-B 2021 IBC", "solar"),
        ("residential photovoltaic array", "solar"),
        ("solar pv system", "solar"),
        ("FAKE STORE - SOLAR PANELS", "solar"),
        ("North Eldridge - Solar System (Roof)", "solar"),
        ("Drake Plastics Solar Permit", "solar"),
        ("Solar Turbines", "other"),
        ("SEG SOLAR", "other"),
        ("SOLARA SURGICAL", "other"),
        ("Solar Shade - window tinting", "other"),
        ("Harris County Community Solar", "other"),
        ("Electric Vehicle Charging Systems", "ev_charger"),
        ("EV CHARGING STATION 2021 IBC", "ev_charger"),
        ("EV CHARGER INSTALL W/PARKING IMPROVEMENT", "ev_charger"),
        ("VEHICLE CHARGING STATION INSTALLATION W/SITEWORK 21 IBC", "ev_charger"),
        ("APARTMENT EV CHARGER INSTALL 2021 IBC", "ev_charger"),
        ("Off-Grid Solar EVSE Pilot", "ev_charger"),
        ("Charging Station", "other"),
        ("Residential, New 1 Family (Standalone Structure)", "new_home"),
        ("Residential, New 1 Family (Attached Townhome)", "new_home"),
        ("Model Home New 1 Family (Detached)", "new_home"),
        ("Residential, New 1 Family (Shares Common Wall)", "new_home"),
        ("new single-family residence", "new_home"),
        ("NEW 1-FAMILY", "new_home"),
        ("new one-family home", "new_home"),
        ("S.F. RES W/ATT. GARAGE (1-2-5-R3-B) 21 IRC/21 IECC", "new_home"),
        ("QS2 S.F. RES W/ATT. GARAGE (1-2-5-R3-B) 21 IRC/21 IECC", "new_home"),
        ("S.F. RES. NO . GAR (REPEAT MODEL- CREATE 2565-3) 21 IRC/21 IECC", "new_home"),
        ("Residential, New 2 Family (Duplex)", "other"),
        ("New Residential, Elevated Structure", "other"),
        ("DUPLEX RES W/ATT. GARAGE (1-2-5-R3-B) 21 IRC/21 IECC", "other"),
        ("SF RESIDENTIAL FOUNDATION REPAIR 1-1-5-R3-B 2021 IRC", "other"),
        ("PPR SF RESIDENTIAL REMODEL AND GARAGE CONVERSION", "other"),
        ("MINOR RESIDENTIAL REPAIRS, SINGLE FAMILY RESIDENTIAL", "other"),
        ("PPR DUPLEX CONVERSION TO SINGLE FAMILY RESIDENTIAL", "other"),
        ("NEW RES. SWIMMING POOL 1-2-5-R3-B 2021 IRC", "other"),
        ("NEW RESIDENTIAL FENCE, 2021 IRC", "other"),
        ("", "other"),
        ("   ", "other"),
    ],
)
def test_classify(text: str, expected: str) -> None:
    assert classify(text) == expected


def test_harris_parse() -> None:
    frame = harris_permits.parse(
        [FIXTURES / "harris_page.json", FIXTURES / "harris_state_plane.json"]
    )
    assert list(frame.columns) == PERMIT_COLUMNS
    assert set(frame["category"]) <= {"solar", "ev_charger", "new_home"}
    assert set(frame["source"]) == {"harris_county_issued_permits"}

    by_id = {row.permit_id: row for row in frame.itertuples(index=False)}
    dropped = {
        "H-DROP-DUPLEX",
        "H-DROP-COMPANY",
        "H-DROP-CHARGE",
        "H-DROP-TURBINE",
        "H-DROP-SOLARA",
    }
    assert dropped.isdisjoint(by_id)
    assert set(by_id) == {
        "H-SOLAR-1",
        "H-EV-1",
        "H-NEW-1",
        "H-NEW-2",
        "H-SOLAR-2",
        "H-NEW-3",
        "H-NEW-4",
        "H-EV-2",
        "H-SOLAR-3",
        "H-EV-3",
        "H-NEW-5",
        "H-NEW-6",
        "H-NEW-7",
        "H-SOLAR-NODATE",
        "H-SOLAR-SP",
    }

    solar = by_id["H-SOLAR-1"]
    assert solar.category == "solar"
    assert solar.address == "100 FAKE ST"
    assert solar.city == "HUMBLE"
    assert solar.zip == "77346"
    assert solar.issued_date == date(2026, 9, 25)
    assert solar.lat == pytest.approx(29.76)
    assert solar.lon == pytest.approx(-95.37)
    assert solar.description == "Solar Photovoltaic Power System | FAKE BANK"

    assert by_id["H-EV-1"].category == "ev_charger"
    assert by_id["H-EV-1"].issued_date == date(2026, 9, 8)
    assert by_id["H-EV-1"].city == "KATY"
    assert by_id["H-NEW-1"].category == "new_home"
    assert by_id["H-NEW-1"].issued_date == date(2026, 5, 5)
    assert by_id["H-NEW-2"].city == "NEW CANEY"
    assert by_id["H-SOLAR-2"].category == "solar"
    assert by_id["H-SOLAR-2"].address == "500 FAKE HWY STE C"
    assert by_id["H-SOLAR-2"].city == "HOCKLEY"
    assert _cell(by_id["H-NEW-3"].city) is None
    assert by_id["H-NEW-3"].zip == "77032"
    assert by_id["H-NEW-3"].address == "600 FAKE BLVD"
    assert by_id["H-NEW-4"].address == "700 FAKE AVE"
    assert by_id["H-NEW-4"].city == "HOUSTON"
    assert by_id["H-NEW-4"].zip == "77070"
    assert by_id["H-EV-2"].category == "ev_charger"
    assert _cell(by_id["H-SOLAR-3"].lat) is None
    assert _cell(by_id["H-SOLAR-3"].lon) is None
    assert by_id["H-EV-3"].category == "ev_charger"
    assert by_id["H-NEW-5"].city == "HOCKLEY"
    assert by_id["H-NEW-5"].zip == "77447"
    assert by_id["H-NEW-6"].address == "1600 FAKE PKWY NO. 2"
    assert by_id["H-NEW-6"].city == "HOUSTON"
    assert by_id["H-NEW-7"].address == "1700 INTERSTATE HWY 10 HWY"
    assert by_id["H-NEW-7"].city == "BAYTOWN"
    assert _cell(by_id["H-SOLAR-NODATE"].issued_date) is None
    # State-plane coordinates must not be reported as lon/lat.
    assert by_id["H-SOLAR-SP"].category == "solar"
    assert _cell(by_id["H-SOLAR-SP"].lat) is None
    assert _cell(by_id["H-SOLAR-SP"].lon) is None


def test_houston_parse() -> None:
    frame = houston_permits.parse(
        [
            FIXTURES / "houston_sept.xlsx",
            FIXTURES / "houston_january.xlsx",
            FIXTURES / "houston_week.xls",
        ]
    )
    assert list(frame.columns) == PERMIT_COLUMNS
    assert set(frame["category"]) <= {"solar", "ev_charger", "new_home"}
    assert set(frame["source"]) == {"houston_weekly_sold_permits"}
    assert set(frame["city"]) == {"Houston"}
    assert frame["lat"].isna().all()
    assert frame["lon"].isna().all()

    by_id = {row.permit_id: row for row in frame.itertuples(index=False)}
    assert set(by_id) == {
        "26065090",
        "26065091",
        "26065092",
        "26065093",
        "26065094",
        "26065095",
        "26065100",
        "25081710",
        "26019999",
    }
    assert by_id["26065090"].category == "solar"
    assert by_id["26065090"].address == "1 FAKE ST"
    assert by_id["26065090"].zip == "77002"
    assert by_id["26065090"].issued_date == date(2026, 9, 9)
    assert by_id["26065090"].description == "Building Pmt | NEW RESIDENTIAL SOLAR PANELS 2021 IRC"
    assert by_id["26065091"].category == "new_home"
    assert by_id["26065092"].category == "ev_charger"
    assert by_id["26065093"].category == "ev_charger"
    assert by_id["26065094"].category == "solar"
    assert by_id["26065095"].category == "new_home"
    assert by_id["26065100"].category == "solar"
    assert by_id["25081710"].category == "new_home"
    assert by_id["25081710"].issued_date == date(2026, 1, 7)
    assert by_id["26019999"].category == "solar"
    assert by_id["26019999"].address == "10 FAKE ST"
    assert by_id["26019999"].issued_date == date(2026, 4, 30)


def test_parse_empty() -> None:
    for adapter in (harris_permits, houston_permits):
        frame = adapter.parse([])
        assert list(frame.columns) == PERMIT_COLUMNS
        assert frame.empty


def test_houston_workbook_links() -> None:
    host = "https://www.houstonpermittingcenter.org/sites/g/files/nwywnm431/files"
    sept = f"{host}/2026-09/Sept%207-13.xlsx"
    august = f"{host}/2026-09/Aug%2024-30_0.xlsx"
    # Office viewer links double-encode spaces (%2520) and escape the ampersand.
    viewer = "https://view.officeapps.live.com/op/view.aspx?src=" + august.replace("%", "%25")
    old_host = "http://hpc.hpwtech.acsitefactory.com/sites/g/files/nwywnm431/files"
    april = f"{old_host}/2026-04/April%2020_26.xls"
    html = (
        f'<a href="{sept}">September 7, 2026</a>'
        f'<a href="{viewer}&amp;wdOrigin=BROWSELINK">August 24, 2026</a>'
        f'<a href="{april}">April 20, 2026</a>'
        '<a href="/media/11111">December 1, 2025</a>'
        '<a href="/help/frequently-asked-questions">FAQ</a>'
    )
    assert houston_permits._spreadsheet_urls(html) == [april, august, sept]
