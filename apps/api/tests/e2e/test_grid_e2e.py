"""Grid Zones end to end: prices in Postgres -> compute -> HTTP API."""

import numpy as np
import pandas as pd

from app.grid.__main__ import compute
from app.grid.store import upsert_prices
from app.grid.zones import TRACKED_POINTS, ZONES


def synthetic_prices() -> pd.DataFrame:
    end = pd.Timestamp.now(tz="UTC").floor("15min") - pd.Timedelta(hours=1)
    rt_index = pd.date_range(end=end, periods=4 * 96, freq="15min")
    da_index = pd.date_range(end=end.floor("1h"), periods=4 * 24, freq="1h")
    frames = []
    for i, point in enumerate(TRACKED_POINTS):
        # Same daily shape everywhere; later zones get a bigger evening peak.
        for market, index in (("RT", rt_index), ("DA", da_index)):
            hour = index.tz_convert("America/Chicago").hour
            price = 25 + np.where((hour >= 17) & (hour <= 21), 60 + 10 * i, 0)
            frames.append(
                pd.DataFrame(
                    {
                        "settlement_point": point,
                        "market": market,
                        "interval_start": index,
                        "price": price.astype(float),
                    }
                )
            )
    return pd.concat(frames, ignore_index=True)


def test_grid_zones_from_prices(client):
    assert client.get("/grid/zones").json() == []
    upsert_prices(synthetic_prices())
    compute()

    zones = client.get("/grid/zones").json()
    assert [z["rank"] for z in zones] == list(range(1, len(ZONES) + 1))
    assert {z["code"] for z in zones} == {z.code for z in ZONES}
    # The zone with the largest evening peak earns the most arbitrage and ranks first.
    assert zones[0]["code"] == ZONES[-1].code
    assert zones[0]["drivers"][0]["key"] == "arbitrage"

    detail = client.get(f"/grid/zones/{zones[0]['code']}").json()
    assert len(detail["series"]["hourly_profile"]) == 24
    assert detail["assumptions"]["battery"]["capacity_kwh"] > 0
    assert client.get("/grid/zones/LZ_NOPE").status_code == 404
