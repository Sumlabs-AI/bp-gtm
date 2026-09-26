"""Storm Exposure: Warning-days under SV/TO/EW polygons on the statewide H3 res-6 grid."""

from datetime import date

import pandas as pd
import pytest
from shapely.geometry import box

from app import geo
from app.need.weather.storms import storm_features, warning_cells

HOUSTON = (29.76, -95.37)
AUSTIN = (30.27, -97.74)
H6 = geo.latlng_to_cell(*HOUSTON, resolution=6)
A6 = geo.latlng_to_cell(*AUSTIN, resolution=6)


def warning(lat, lng, issued, phenom="SV", sig="W", gtype="P", etn=1, size=0.2, wfo="HGX"):
    return {
        "wfo": wfo,
        "phenom": phenom,
        "sig": sig,
        "gtype": gtype,
        "etn": etn,
        "issued": pd.Timestamp(issued, tz="UTC"),
        "geometry": box(lng - size, lat - size, lng + size, lat + size),
    }


def cells_of(rows):
    return warning_cells(pd.DataFrame(rows))


def test_polygon_covers_res6_cells_on_its_local_day():
    hits = cells_of([warning(*HOUSTON, "2024-05-17 02:00")])  # 21:00 CDT on May 16
    assert set(hits["h3_index"]).issuperset({H6})
    assert set(hits["day"]) == {date(2024, 5, 16)}
    assert all(geo.cell_resolution(h) == 6 for h in hits["h3_index"])


def test_only_severe_tornado_and_extreme_wind_warnings_count():
    rows = [
        warning(*HOUSTON, "2024-05-16 20:00", phenom="SV", etn=1),
        warning(*HOUSTON, "2024-05-16 20:00", phenom="TO", etn=2),
        warning(*HOUSTON, "2024-07-08 10:00", phenom="EW", etn=3),
        warning(*HOUSTON, "2024-06-01 10:00", phenom="FF", etn=4),  # flash flood: out
        warning(*HOUSTON, "2024-06-02 10:00", phenom="SV", sig="A", etn=5),  # watch: out
        warning(*HOUSTON, "2024-06-03 10:00", phenom="SV", gtype="C", etn=6),  # county row: out
    ]
    assert set(cells_of(rows)["phenom"]) == {"SV", "TO", "EW"}


def test_tiny_polygon_falls_back_to_its_centroid_cell():
    hits = cells_of([warning(*HOUSTON, "2024-05-16 20:00", size=0.001)])
    assert hits["h3_index"].tolist() == [geo.latlng_to_cell(*HOUSTON, resolution=6)]


def test_features_count_days_not_warnings_and_rank_the_grid():
    rows = [
        # Houston: two warnings the same local day (one storm) + one more day + one old day.
        warning(*HOUSTON, "2025-05-16 20:00", etn=1),
        warning(*HOUSTON, "2025-05-16 23:00", phenom="TO", etn=2),
        warning(*HOUSTON, "2025-07-08 15:00", etn=3),
        warning(*HOUSTON, "2021-06-01 15:00", etn=4),
        # Austin: one day.
        warning(*AUSTIN, "2025-04-01 15:00", etn=5, wfo="EWX"),
    ]
    grid = [H6, A6, geo.latlng_to_cell(32.0, -102.0, resolution=6)]  # + a quiet cell
    features = storm_features(cells_of(rows), grid, data_through=date(2025, 12, 31))
    features = features.set_index("h3_index")

    houston = features.loc[H6]
    assert houston.warning_days_5y == 3
    assert houston.warning_days_365d == 2
    assert (houston.severe_thunderstorm_warnings_5y, houston.tornado_warnings_5y) == (3, 1)
    assert features.loc[A6, "warning_days_5y"] == 1
    quiet = features.loc[grid[2]]
    assert quiet.warning_days_5y == 0  # no warnings: genuinely zero, still ranked
    assert houston.storm_exposure == pytest.approx(500 / 6)
    assert quiet.storm_exposure == pytest.approx(100 / 6)
    assert (features["resolution"] == 6).all()
    assert (features["data_through"] == date(2025, 12, 31)).all()


def test_windows_end_at_data_through():
    rows = [
        warning(*HOUSTON, "2020-12-31 18:00", etn=1),
        warning(*HOUSTON, "2026-01-02 18:00", etn=2),
    ]
    features = storm_features(cells_of(rows), [H6], data_through=date(2025, 12, 31))
    assert features.iloc[0].warning_days_5y == 0  # one day before the window, one after


def test_res8_cell_resolves_its_res6_parent():
    cell = geo.latlng_to_cell(*HOUSTON)
    assert geo.cell_to_parent(cell, 6) == H6
