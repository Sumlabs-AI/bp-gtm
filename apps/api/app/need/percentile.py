"""Percentiles against a Reference Population (e.g. all Texas counties with usable data)."""

import pandas as pd


def percentile_rank(values: pd.Series, population: pd.Series | None = None) -> pd.Series:
    """0-100 midrank percentile of each value; higher value = higher percentile.

    Ties share their average rank. Missing values, and rows outside `population` (a boolean
    mask on the same index), get no percentile (NaN) and don't count toward n.
    """
    ranked = (
        values.where(population.reindex(values.index, fill_value=False))
        if population is not None
        else values
    )
    ranked = ranked.dropna()
    pct = (ranked.rank(method="average") - 0.5) / len(ranked) * 100
    return pct.reindex(values.index)
