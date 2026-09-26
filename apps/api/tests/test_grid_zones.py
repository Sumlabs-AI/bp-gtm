"""The one Load Zone rule (app.grid.zones.zone_for_points), shared by Leads and Cells."""

import pandas as pd

from app.grid.zones import zone_for_points

PLACES = pd.DataFrame(
    [
        ("houston", 29.7604, -95.3698, "LZ_HOUSTON"),
        ("dallas", 32.7767, -96.7970, "LZ_NORTH"),
        ("corpus_christi", 27.8006, -97.3964, "LZ_SOUTH"),
        ("midland", 31.9973, -102.0779, "LZ_WEST"),
        # Municipal territories sit inside LZ_SOUTH: the smaller polygon wins.
        ("austin", 30.2672, -97.7431, "LZ_AEN"),
        ("san_antonio", 29.4241, -98.4936, "LZ_CPS"),
        ("gulf_of_mexico", 27.0, -94.0, None),
    ],
    columns=["name", "lat", "lon", "expected"],
).set_index("name")


def test_points_get_the_zone_they_fall_in():
    zones = zone_for_points(PLACES["lat"], PLACES["lon"])
    expected = {name: (None if pd.isna(z) else z) for name, z in PLACES["expected"].items()}
    assert zones.to_dict() == expected


def test_result_follows_the_input_index():
    shuffled = PLACES.iloc[::-1]
    zones = zone_for_points(shuffled["lat"], shuffled["lon"])
    assert list(zones.index) == list(shuffled.index)
    assert zones["austin"] == "LZ_AEN"


def test_missing_coordinates_have_no_zone():
    zones = zone_for_points(pd.Series([None, 29.7604]), pd.Series([None, -95.3698]))
    assert zones.tolist() == [None, "LZ_HOUSTON"]
