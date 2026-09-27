"""Opportunity Score: weighted geometric mean of Propensity and Baseline Need."""

import pytest

from app.need.config import opportunity as config
from app.need.opportunity import LeadCells, opportunity_score, pick_lead_cells


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


def test_lead_cells_are_the_top_cells_of_each_county():
    cells = [
        ("harris", "a", 10, 80.0),
        ("harris", "b", 10, 70.0),
        ("harris", "c", 80, 60.0),
        ("travis", "x", 15, 50.0),
        ("travis", "y", 85, 40.0),
    ]
    # 15% of Harris (15 homes): "a" holds 10, "b" crosses the line. Travis: "x" alone
    # (15 >= 15), although its score is below every Harris Cell.
    assert pick_lead_cells(cells, 0.15) == {
        "harris": LeadCells({"a", "b"}, 70.0),
        "travis": LeadCells({"x"}, 50.0),
    }


def test_lead_cells_skip_unscored_cells():
    cells = [("harris", "a", 90, None), ("harris", "b", 10, 50.0)]
    assert pick_lead_cells(cells, 0.5) == {"harris": LeadCells({"b"}, 50.0)}
    assert pick_lead_cells([("harris", "a", 90, None)], 0.5) == {}
