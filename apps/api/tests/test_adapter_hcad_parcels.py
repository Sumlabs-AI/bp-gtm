from pathlib import Path

import pytest
from pyproj import Transformer

from app.leads.adapters import hcad_parcels
from app.leads.frames import PARCEL_COLUMNS

FIXTURE = Path(__file__).parent / "fixtures" / "leads" / "hcad_parcels" / "Parcels.zip"


def test_parse_gives_one_wgs84_point_per_account():
    frame = hcad_parcels.parse([FIXTURE])
    assert frame.columns.tolist() == PARCEL_COLUMNS
    assert sorted(frame["account"]) == ["0000000000001", "0000000000002"]
    # State plane feet -> Houston-area lat/lon.
    assert frame["lat"].between(29, 31).all() and frame["lon"].between(-96, -94).all()
    # Account 2 also has a tiny stacked polygon in a corner; the point comes from the
    # larger parcel, i.e. its center (3121100, 13841100) in state plane feet.
    lon, lat = Transformer.from_crs(2278, 4326, always_xy=True).transform(3121100, 13841100)
    point = frame.set_index("account").loc["0000000000002"]
    assert point["lat"] == pytest.approx(lat, abs=1e-5)
    assert point["lon"] == pytest.approx(lon, abs=1e-5)
