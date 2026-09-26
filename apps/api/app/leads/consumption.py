"""Property-based estimate of a home's electricity use (v1: no bill, no meter data).

- Annual kWh and summer/winter peak kW: log-linear fits on HCAD-style features (size,
  vintage, stories, bedrooms, pool), one set for electric-heat homes and one for the rest,
  fitted on NREL ResStock's simulated Harris County single-family homes and scaled to EIA
  RECS (scripts/fit_consumption_model.py writes consumption_model.json).
- Heating fuel isn't in any per-home public record, so each home mixes the two fits by
  P(electric heat): its Census block group's electric-heat share, shifted so the county
  average matches ResStock's owner-occupied single-family share.
- Monthly shape: ERCOT's Houston-area residential load profiles (RESHIWR for electric
  heat, RESLOWR otherwise), averaged over full past years.

A screening estimate: expect roughly ±30–40% per home on annual kWh and more on peaks.
See wiki/residential-leads.md and ideas/home-consumption-from-meter-data.md.
"""

import json
from functools import cache
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.special import expit, logit, ndtr

from app.leads.census import block_group_heating

MODEL_FILE = Path(__file__).with_name("consumption_model.json")
FUELS = ("electric", "other")
SHAPES = {"electric": "RESHIWR", "other": "RESLOWR"}  # ERCOT profile per heating fuel
Z90 = 1.2815515655446004  # standard normal 90th percentile: P10–P90 range


@cache
def load_model(path: Path = MODEL_FILE) -> dict:
    return json.loads(path.read_text())


def design(
    sqft: np.ndarray,
    year_built: np.ndarray,
    stories: np.ndarray,
    bedrooms: np.ndarray,
    pool: np.ndarray,
) -> np.ndarray:
    """Feature matrix shared by the fit (ResStock) and scoring (HCAD). No missing values."""
    decade = (np.clip(year_built, 1930, 2025) - 1980) / 10
    return np.column_stack(
        [
            np.ones(len(sqft)),
            np.log(np.clip(sqft, 400, 8000)),
            decade,
            decade**2,
            (stories >= 1.5).astype(float),
            np.clip(bedrooms, 1, 5),
            pool.astype(float),
        ]
    )


def home_features(homes: pd.DataFrame, model: dict) -> np.ndarray:
    """Design matrix for HCAD homes; missing fields take the model's typical values."""
    d = model["defaults"]
    return design(
        homes["heated_sqft"].astype(float).fillna(d["sqft"]).to_numpy(),
        homes["year_built"].astype(float).fillna(d["year_built"]).to_numpy(),
        homes["stories"].astype(float).fillna(d["stories"]).to_numpy(),
        homes["bedrooms"].astype(float).fillna(d["bedrooms"]).to_numpy(),
        homes["has_pool"].fillna(False).astype(bool).to_numpy(),
    )


def electric_heat_prob(
    homes: pd.DataFrame, model: dict, block_groups: gpd.GeoDataFrame | None = None
) -> pd.Series:
    """P(electric heat) per home from its block group's share, recentered on the model's
    county share (ACS counts apartments, which in Houston are more often electric)."""
    if block_groups is None:
        block_groups = block_group_heating()
    shares = block_groups.dropna(subset=["electric_share"])
    target = model["electric_heat_share"]
    located = homes[["lat", "lon"]].dropna()
    points = gpd.GeoDataFrame(
        index=located.index, geometry=gpd.points_from_xy(located["lon"], located["lat"]), crs=4326
    )
    hits = gpd.sjoin(points, shares[["electric_share", "geometry"]], predicate="within")
    share = hits.groupby(level=0)["electric_share"].first().reindex(homes.index)
    base = logit(share.clip(0.02, 0.98).to_numpy())
    known = ~np.isnan(base)
    if not known.any():
        return pd.Series(target, index=homes.index)
    # Shift in log-odds so the average over these homes equals the target share.
    lo, hi = -10.0, 10.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if expit(base[known] + mid).mean() < target:
            lo = mid
        else:
            hi = mid
    prob = np.where(known, expit(base + (lo + hi) / 2), target)
    return pd.Series(prob, index=homes.index)


def _mixture_quantile(q: float, p: np.ndarray, mus: list, sigmas: list) -> np.ndarray:
    """Quantile of p·LogNormal(mu_e, s_e) + (1−p)·LogNormal(mu_o, s_o), in log space."""
    lo = np.minimum(mus[0] - 5 * sigmas[0], mus[1] - 5 * sigmas[1])
    hi = np.maximum(mus[0] + 5 * sigmas[0], mus[1] + 5 * sigmas[1])
    for _ in range(50):
        mid = (lo + hi) / 2
        cdf = p * ndtr((mid - mus[0]) / sigmas[0]) + (1 - p) * ndtr((mid - mus[1]) / sigmas[1])
        below = cdf < q
        lo, hi = np.where(below, mid, lo), np.where(below, hi, mid)
    return (lo + hi) / 2


def estimate(homes: pd.DataFrame, prob: pd.Series, model: dict | None = None) -> pd.DataFrame:
    """Per home: annual_kwh (median), low_kwh/high_kwh (P10–P90), monthly_kwh (12 values
    summing to annual_kwh), peak_summer_kw, peak_winter_kw, electric_heat_prob."""
    model = model or load_model()
    x = home_features(homes, model)
    p = prob.to_numpy(dtype=float)
    scale = np.log(model["calibration"]["factor"])
    mu = {
        k: {f: x @ np.array(model["fits"][f][k]["coef"]) + scale for f in FUELS}
        for k in ("annual_kwh", "peak_summer_kw", "peak_winter_kw")
    }
    sigma = [model["fits"][f]["annual_kwh"]["sigma"] for f in FUELS]
    annual_mus = [mu["annual_kwh"][f] for f in FUELS]
    median = np.exp(_mixture_quantile(0.5, p, annual_mus, sigma))
    low = np.exp(_mixture_quantile(ndtr(-Z90), p, annual_mus, sigma))
    high = np.exp(_mixture_quantile(ndtr(Z90), p, annual_mus, sigma))

    # Monthly shape: the two ERCOT profiles weighted by each fuel's share of expected use.
    weight = p * np.exp(annual_mus[0])
    weight = weight / (weight + (1 - p) * np.exp(annual_mus[1]))
    shares = {f: np.array(model["monthly_shares"][SHAPES[f]]) for f in FUELS}
    shape = np.outer(weight, shares["electric"]) + np.outer(1 - weight, shares["other"])
    monthly = shape / shape.sum(axis=1, keepdims=True) * median[:, None]

    def peak(key: str) -> np.ndarray:
        return p * np.exp(mu[key]["electric"]) + (1 - p) * np.exp(mu[key]["other"])

    return pd.DataFrame(
        {
            "annual_kwh": median.round(-1),
            "low_kwh": low.round(-1),
            "high_kwh": high.round(-1),
            "monthly_kwh": [list(row) for row in monthly.round()],
            "peak_summer_kw": peak("peak_summer_kw").round(1),
            "peak_winter_kw": peak("peak_winter_kw").round(1),
            "electric_heat_prob": p.round(2),
        },
        index=homes.index,
    )
