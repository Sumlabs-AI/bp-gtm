import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from app.leads.consumption import electric_heat_prob, estimate, load_model

FLAT = [1 / 12] * 12
WINTER = [0.14, 0.12, 0.08, 0.06, 0.06, 0.07, 0.08, 0.08, 0.07, 0.06, 0.08, 0.10]


def fit(intercept: float, sigma: float = 0.3) -> dict:
    # log(kWh) = intercept + 1.0·log(sqft) + … + 0.2·pool
    coef = [intercept, 1.0, 0.0, 0.0, 0.0, 0.0, 0.2]
    return {"coef": coef, "sigma": sigma}


MODEL = {
    "defaults": {"sqft": 2000.0, "year_built": 1985.0, "stories": 1.0, "bedrooms": 3.0},
    "electric_heat_share": 0.3,
    "calibration": {"factor": 1.0},
    "fits": {
        "electric": {
            "annual_kwh": fit(2.5),
            "peak_summer_kw": fit(-5.0),
            "peak_winter_kw": fit(-4.5),
        },
        "other": {"annual_kwh": fit(2.2), "peak_summer_kw": fit(-5.0), "peak_winter_kw": fit(-5.5)},
    },
    "monthly_shares": {"RESHIWR": WINTER, "RESLOWR": FLAT},
}


def homes(**overrides) -> pd.DataFrame:
    base = {
        "heated_sqft": 2000.0,
        "year_built": 1985,
        "stories": 1.0,
        "bedrooms": 3,
        "has_pool": False,
        "lat": 29.76,
        "lon": -95.37,
    }
    return pd.DataFrame([base | overrides])


def run(frame: pd.DataFrame, prob: float) -> pd.Series:
    return estimate(frame, pd.Series(prob, index=frame.index), MODEL).iloc[0]


def test_monthly_sums_to_annual_inside_its_range():
    row = run(homes(), 0.5)
    assert len(row.monthly_kwh) == 12
    assert sum(row.monthly_kwh) == pytest.approx(row.annual_kwh, abs=15)
    assert row.low_kwh < row.annual_kwh < row.high_kwh


def test_known_fuel_is_the_lognormal_median_and_p10_p90():
    other = run(homes(), 0.0)
    assert other.annual_kwh == pytest.approx(np.exp(2.2) * 2000, abs=5)
    assert other.high_kwh / other.annual_kwh == pytest.approx(np.exp(1.2816 * 0.3), rel=0.01)
    electric = run(homes(), 1.0)
    assert electric.annual_kwh == pytest.approx(np.exp(2.5) * 2000, abs=5)
    # Electric heat uses the winter-heavy shape; other homes the flat one here.
    assert electric.monthly_kwh[0] > electric.monthly_kwh[4]
    assert other.monthly_kwh[0] == pytest.approx(other.monthly_kwh[4], abs=1)
    assert electric.peak_winter_kw > other.peak_winter_kw


def test_bigger_homes_and_pools_use_more():
    small, big = run(homes(heated_sqft=1500.0), 0.3), run(homes(heated_sqft=3000.0), 0.3)
    assert big.annual_kwh > small.annual_kwh
    assert run(homes(has_pool=True), 0.3).annual_kwh > run(homes(), 0.3).annual_kwh


def test_missing_fields_use_model_defaults():
    missing = homes(heated_sqft=None, year_built=None, stories=None, bedrooms=None)
    assert run(missing, 0.3).annual_kwh == run(homes(), 0.3).annual_kwh


def test_electric_heat_prob_follows_block_groups_and_hits_the_target():
    groups = gpd.GeoDataFrame(
        {"electric_share": [0.2, 0.8]},
        geometry=[box(-96, 29, -95.5, 30), box(-95.5, 29, -95, 30)],
        crs=4326,
    )
    frame = pd.DataFrame(
        {"lat": [29.5, 29.5, 29.5, 29.5, 35.0], "lon": [-95.8, -95.7, -95.2, -95.1, -90.0]}
    )
    prob = electric_heat_prob(frame, MODEL, groups)
    assert prob[:4].mean() == pytest.approx(0.3, abs=1e-6)  # recentered on the target
    assert prob[0] == prob[1] < prob[2] == prob[3]  # order of the block-group shares kept
    assert prob[4] == 0.3  # outside every block group: the county share


def test_fitted_model_is_plausible_for_a_typical_houston_home():
    model = load_model()
    row = estimate(homes(), pd.Series(model["electric_heat_share"], index=[0]), model).iloc[0]
    assert 8_000 < row.annual_kwh < 25_000
    assert row.monthly_kwh[6] > row.monthly_kwh[1]  # July above February
    assert 3 < row.peak_summer_kw < 20
