"""Baseline Need: union-style combination of Outage and Weather, ranked against Texas."""

import numpy as np
import pytest

from app.need.baseline import dominant_driver, reference_percentile, soft_or


def test_soft_or_is_a_union_style_combination():
    assert soft_or(61.0, 31.0) == pytest.approx(73.09)
    assert soft_or(0.0, 0.0) == 0.0
    assert soft_or(100.0, 12.0) == 100.0
    assert soft_or(50.0, 50.0) == 75.0
    # One strong reason is never diluted by a weak one (unlike a mean)...
    assert soft_or(80.0, 10.0) > 80.0
    # ...and it's monotonic in both inputs.
    assert soft_or(60.0, 40.0) < soft_or(61.0, 40.0) < soft_or(61.0, 41.0)


def test_a_missing_input_leaves_the_other_alone():
    assert soft_or(None, 42.0) == 42.0
    assert soft_or(42.0, None) == 42.0
    assert soft_or(None, None) is None


def test_dominant_driver_names_the_input_that_explains_most():
    assert dominant_driver(76.0, 31.0) == "outage"
    assert dominant_driver(20.0, 60.0) == "weather"
    assert dominant_driver(50.0, 58.0) == "both"  # within 10 points
    assert dominant_driver(None, 40.0) == "weather"
    assert dominant_driver(40.0, None) == "outage"
    assert dominant_driver(50.0, 60.0) == "both"  # exactly 10 apart: still "both"
    assert dominant_driver(None, None) is None


def test_percentile_is_midrank_within_the_reference():
    reference = np.sort(np.array([10.0, 20.0, 20.0, 30.0, 40.0]))
    assert reference_percentile(25.0, reference) == 60.0  # 3 below, of 5
    assert reference_percentile(20.0, reference) == 40.0  # 1 below + half of 2 ties
    assert reference_percentile(5.0, reference) == 0.0
    assert reference_percentile(99.0, reference) == 100.0
    assert reference_percentile(None, reference) is None
