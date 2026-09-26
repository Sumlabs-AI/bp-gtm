import pytest

from app.leads.config import LeadScoringConfig
from app.leads.value import recommend_battery

CFG = LeadScoringConfig()


@pytest.mark.parametrize(
    ("sqft", "pool", "kwh", "reason"),
    [
        (1_800, False, 25, "1,800 sqft home → 25 kWh"),
        (2_500, False, 40, "2,500 sqft home → 40 kWh"),
        (3_100, True, 50, "3,100 sqft home with a pool → 50 kWh"),
        (5_000, True, 50, "5,000 sqft home with a pool → 50 kWh"),  # already the largest
        (None, False, 25, "Home of unknown size → 25 kWh"),
        (float("nan"), True, 40, "Home of unknown size with a pool → 40 kWh"),
    ],
)
def test_recommend_battery(sqft, pool, kwh, reason):
    assert recommend_battery(sqft, pool, CFG) == (kwh, reason)
