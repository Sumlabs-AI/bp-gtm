"""Opportunity Score: weighted geometric mean of Propensity and Baseline Need."""

import pytest

from app.need.config import opportunity as config
from app.need.opportunity import opportunity_score


def test_weights_sum_to_one():
    assert config.propensity_weight + config.need_weight == pytest.approx(1.0)


def test_opportunity_score():
    assert opportunity_score(90.0, 70.0) == pytest.approx(81.5, abs=0.1)
    assert opportunity_score(100.0, 100.0) == 100.0
    assert opportunity_score(50.0, 50.0) == 50.0
    # Both are needed: a zero in either gives zero.
    assert opportunity_score(0.0, 100.0) == 0.0
    assert opportunity_score(100.0, 0.0) == 0.0
    # Propensity weighs more than Need.
    assert opportunity_score(80.0, 40.0) > opportunity_score(40.0, 80.0)


def test_missing_input_gives_no_score():
    assert opportunity_score(None, 50.0) is None
    assert opportunity_score(50.0, None) is None


def test_timing_multiplies_the_score():
    assert opportunity_score(50.0, 50.0, 1.5) == 75.0
    assert opportunity_score(100.0, 100.0, 1.5) == 150.0  # not capped: order holds in a storm area
    assert opportunity_score(None, 50.0, 1.5) is None
