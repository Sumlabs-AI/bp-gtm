"""Texas percentiles: rank a raw metric within its Reference Population, 0-100."""

import math

import pandas as pd

from app.need.percentile import percentile_rank


def test_higher_values_rank_higher():
    ranks = percentile_rank(pd.Series({"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0, "e": 5.0}))
    # Midrank: (rank - 0.5) / n * 100.
    assert ranks.to_dict() == {"a": 10.0, "b": 30.0, "c": 50.0, "d": 70.0, "e": 90.0}


def test_ties_share_the_average_rank():
    ranks = percentile_rank(pd.Series({"a": 1.0, "b": 2.0, "c": 2.0, "d": 3.0}))
    assert ranks["b"] == ranks["c"] == 50.0
    assert (ranks["a"], ranks["d"]) == (12.5, 87.5)


def test_missing_values_stay_missing_and_are_not_ranked():
    ranks = percentile_rank(pd.Series({"a": 1.0, "b": None, "c": 3.0}))
    assert math.isnan(ranks["b"])
    assert (ranks["a"], ranks["c"]) == (25.0, 75.0)


def test_only_the_population_is_ranked():
    values = pd.Series({"a": 1.0, "b": 100.0, "c": 3.0})
    ranks = percentile_rank(values, population=pd.Series({"a": True, "b": False, "c": True}))
    assert math.isnan(ranks["b"])  # outside the Reference Population: no percentile
    assert (ranks["a"], ranks["c"]) == (25.0, 75.0)


def test_deterministic_and_empty():
    values = pd.Series({"x": 5.0, "y": 1.0, "z": 5.0})
    assert percentile_rank(values).equals(
        percentile_rank(values.sample(frac=1, random_state=3)).reindex(values.index)
    )
    assert percentile_rank(pd.Series(dtype=float)).empty
