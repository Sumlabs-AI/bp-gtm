"""Fit the property-based consumption model and write app/leads/consumption_model.json.

Run from apps/api (downloads ~200 MB once into data/raw/consumption_model/):

    uv run python -m scripts.fit_consumption_model

Inputs, all public:
- NREL ResStock 2025.1 (AMY2018) Texas metadata + annual results, CC BY 4.0: simulated homes
  with their features, annual electricity and peak kW. We use Harris County single-family
  detached homes.
- EIA RECS 2020 microdata (public domain): real billed kWh, used to scale ResStock's level
  (ResStock runs ~15–20% high for Texas homes).
- ERCOT backcasted load profiles 2019–2025: monthly shape of RESLOWR/RESHIWR in the COAST
  weather zone (Houston).
"""

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from app.leads.consumption import FUELS, MODEL_FILE, design
from app.leads.pipeline import RAW_DIR

CACHE = RAW_DIR / "consumption_model"
RESSTOCK_URL = (
    "https://oedi-data-lake.s3.amazonaws.com/nrel-pds-building-stock/"
    "end-use-load-profiles-for-us-building-stock/2025/resstock_amy2018_release_1/"
    "metadata_and_annual_results/by_state/full/csv/state=TX/TX_upgrade0.csv.gz"
)
RECS_URL = "https://www.eia.gov/consumption/residential/data/2020/csv/recs2020_public_v7.csv"
ERCOT_PROFILES = {  # from https://www.ercot.com/mktinfo/loadprofile/alp
    2019: "https://www.ercot.com/files/docs/2020/01/03/ERCOT_Backcasted_Load_Profiles_2019.zip",
    2020: "https://www.ercot.com/files/docs/2021/01/07/ERCOT_Backcasted_Load_Profiles_2020.zip",
    2021: "https://www.ercot.com/files/docs/2021/11/05/ERCOT_Backcasted_Load_Profiles_2021.zip",
    2022: "https://www.ercot.com/files/docs/2022/04/04/"
    "ERCOT%20Backcasted%20Load%20Profiles%202022%20-%20Updated%20v2.zip",
    2023: "https://www.ercot.com/files/docs/2023/02/06/ERCOT-Backcasted-Load-Profiles-2023.zip",
    2024: "https://www.ercot.com/files/docs/2024/02/06/ERCOT_Backcasted_Load_Profiles_2024.zip",
    2025: "https://www.ercot.com/files/docs/2025/02/04/ERCOT-Backcasted-Load-Profiles-2025.zip",
}
HARRIS = "G4802010"
VINTAGE_YEAR = {
    "<1940": 1930,
    "1940s": 1945,
    "1950s": 1955,
    "1960s": 1965,
    "1970s": 1975,
    "1980s": 1985,
    "1990s": 1995,
    "2000s": 2005,
    "2010s": 2015,
    "2020s": 2022,
}
TARGETS = {
    "annual_kwh": "out.electricity.total.energy_consumption..kwh",
    "peak_summer_kw": "out.qoi.electricity.maximum_daily_peak_summer..kw",
    "peak_winter_kw": "out.qoi.electricity.maximum_daily_peak_winter..kw",
}
UA = {"User-Agent": "Mozilla/5.0 (base-power-gtm consumption model)"}


def download(url: str, name: str) -> Path:
    path = CACHE / name
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        print(f"downloading {url}")
        with httpx.stream("GET", url, headers=UA, follow_redirects=True, timeout=900) as r:
            r.raise_for_status()
            with path.with_suffix(".part").open("wb") as out:
                for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                    out.write(chunk)
        path.with_suffix(".part").rename(path)
    return path


def resstock_homes() -> pd.DataFrame:
    columns = [
        "weight",
        "in.county",
        "in.geometry_building_type_recs",
        "in.tenure",
        "in.sqft..ft2",
        "in.vintage",
        "in.geometry_stories",
        "in.bedrooms",
        "in.misc_pool",
        "in.heating_fuel",
        *TARGETS.values(),
    ]
    df = pd.read_csv(download(RESSTOCK_URL, "TX_upgrade0.csv.gz"), usecols=columns)
    df = df[
        (df["in.county"] == HARRIS)
        & (df["in.geometry_building_type_recs"] == "Single-Family Detached")
    ]
    return pd.DataFrame(
        {
            "weight": df["weight"],
            "owner": df["in.tenure"] == "Owner",
            "sqft": df["in.sqft..ft2"].astype(float),
            "year_built": df["in.vintage"].map(VINTAGE_YEAR).astype(float),
            "stories": df["in.geometry_stories"].astype(float),
            "bedrooms": df["in.bedrooms"].astype(float),
            "pool": df["in.misc_pool"].eq("Has Pool"),
            "fuel": np.where(df["in.heating_fuel"] == "Electricity", "electric", "other"),
            **{k: df[v].astype(float) for k, v in TARGETS.items()},
        }
    ).dropna()


def wls(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Weighted least squares: coefficients, residual sigma, weighted R²."""
    sw = np.sqrt(w / w.mean())
    coef, *_ = np.linalg.lstsq(x * sw[:, None], y * sw, rcond=None)
    resid = y - x @ coef
    sigma = float(np.sqrt(np.average(resid**2, weights=w)))
    r2 = 1 - np.average(resid**2, weights=w) / np.average(
        (y - np.average(y, weights=w)) ** 2, weights=w
    )
    return coef, sigma, float(r2)


def cross_validated(x, y, w, folds=5, seed=0) -> dict:
    """Out-of-fold R² (log) and absolute % error of exp(prediction), weighted."""
    fold = np.random.default_rng(seed).integers(0, folds, len(y))
    pred = np.empty_like(y)
    for k in range(folds):
        coef, _, _ = wls(x[fold != k], y[fold != k], w[fold != k])
        pred[fold == k] = x[fold == k] @ coef
    ape = np.abs(np.exp(pred) / np.exp(y) - 1)
    r2 = 1 - np.average((y - pred) ** 2, weights=w) / np.average(
        (y - np.average(y, weights=w)) ** 2, weights=w
    )
    order = np.argsort(ape)
    cum = np.cumsum(w[order]) / w.sum()
    return {
        "r2_log": round(float(r2), 3),
        "mape": round(float(np.average(ape, weights=w)), 3),
        "median_ape": round(float(ape[order][np.searchsorted(cum, 0.5)]), 3),
    }


def recs_hot_humid_sfd_kwh() -> float:
    """Weighted mean billed kWh of Texas hot-humid single-family detached homes (RECS 2020)."""
    df = pd.read_csv(
        download(RECS_URL, "recs2020_public_v7.csv"),
        usecols=["state_postal", "TYPEHUQ", "BA_climate", "KWH", "NWEIGHT"],
    )
    df = df[(df["state_postal"] == "TX") & (df["TYPEHUQ"] == 2) & (df["BA_climate"] == "Hot-Humid")]
    print(f"RECS TX hot-humid single-family detached sample: {len(df)} homes")
    return float(np.average(df["KWH"], weights=df["NWEIGHT"]))


def ercot_monthly_shares() -> tuple[dict[str, list[float]], dict[str, float], list[int]]:
    """Mean monthly share of annual kWh (and mean annual kWh) of COAST RESLOWR/RESHIWR."""
    shares, annual, years = {"RESLOWR": [], "RESHIWR": []}, {"RESLOWR": [], "RESHIWR": []}, []
    for year, url in ERCOT_PROFILES.items():
        with zipfile.ZipFile(download(url, f"ercot_backcasted_{year}.zip")) as archive:
            member = next(n for n in archive.namelist() if n.lower().endswith((".xlsx", ".xls")))
            sheets = pd.read_excel(
                io.BytesIO(archive.read(member)), sheet_name=None, engine="calamine"
            )
        frame = pd.concat(sheets.values(), ignore_index=True)
        key = frame.columns[0]
        # Some workbooks repeat a month (2025 has both "September" and "Sep" sheets).
        frame = frame.drop_duplicates(subset=[key, frame.columns[1]])
        date = pd.to_datetime(frame[frame.columns[1]], errors="coerce")
        intervals = [c for c in frame.columns[2:] if str(c).lower().startswith("int")]
        daily = frame[intervals].apply(pd.to_numeric, errors="coerce").sum(axis=1)
        for profile in shares:
            rows = frame[key].astype(str).str.upper() == f"{profile}_COAST"
            by_month = daily[rows].groupby(date[rows].dt.month).sum()
            if len(by_month) != 12:
                raise ValueError(f"{year} {profile}_COAST: only {len(by_month)} months")
            shares[profile].append((by_month / by_month.sum()).to_numpy())
            annual[profile].append(float(by_month.sum()))
        years.append(year)
        print(f"ERCOT {year}: RESLOWR_COAST {annual['RESLOWR'][-1]:,.0f} kWh")
    return (
        {p: [round(float(v), 5) for v in np.mean(s, axis=0)] for p, s in shares.items()},
        {p: round(float(np.mean(a))) for p, a in annual.items()},
        years,
    )


def main() -> None:
    homes = resstock_homes()
    print(f"ResStock Harris single-family detached: {len(homes)} samples")
    x = design(
        homes["sqft"].to_numpy(),
        homes["year_built"].to_numpy(),
        homes["stories"].to_numpy(),
        homes["bedrooms"].to_numpy(),
        homes["pool"].to_numpy(),
    )
    w = homes["weight"].to_numpy(dtype=float)

    fits = {}
    for fuel in FUELS:
        m = (homes["fuel"] == fuel).to_numpy()
        fits[fuel] = {"samples": int(m.sum())}
        for target in TARGETS:
            y = np.log(homes[target].to_numpy()[m])
            coef, sigma, r2 = wls(x[m], y, w[m])
            fits[fuel][target] = {
                "coef": [round(float(c), 6) for c in coef],
                "sigma": round(sigma, 4),
                "r2_log": round(r2, 3),
                "cv": cross_validated(x[m], y, w[m]),
            }
            print(
                f"{fuel:8s} {target:15s} R² {r2:.2f}  σ {sigma:.2f}  CV {fits[fuel][target]['cv']}"
            )

    owners = homes[homes["owner"]]
    electric_share = float(np.average(owners["fuel"] == "electric", weights=owners["weight"]))
    resstock_kwh = float(np.average(homes["annual_kwh"], weights=homes["weight"]))
    recs_kwh = recs_hot_humid_sfd_kwh()
    monthly, ercot_annual, years = ercot_monthly_shares()
    model = {
        "fitted_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sources": {"resstock": RESSTOCK_URL, "recs": RECS_URL, "ercot_profiles": years},
        "features": [
            "intercept",
            "log_sqft",
            "decade",
            "decade_sq",
            "two_story",
            "bedrooms",
            "pool",
        ],
        "defaults": {
            "sqft": float(np.average(owners["sqft"], weights=owners["weight"]).round()),
            "year_built": 1985.0,
            "stories": 1.0,
            "bedrooms": 3.0,
        },
        "electric_heat_share": round(electric_share, 3),
        "calibration": {
            "factor": round(recs_kwh / resstock_kwh, 4),
            "recs_tx_hot_humid_sfd_kwh": round(recs_kwh),
            "resstock_harris_sfd_kwh": round(resstock_kwh),
            "ercot_coast_average_premise_kwh": ercot_annual,
        },
        "fits": fits,
        "monthly_shares": monthly,
    }
    MODEL_FILE.write_text(json.dumps(model, indent=2) + "\n")
    print(
        f"electric-heat share (owners) {electric_share:.1%}; calibration "
        f"{recs_kwh:,.0f} / {resstock_kwh:,.0f} = {recs_kwh / resstock_kwh:.3f}"
    )
    print(f"wrote {MODEL_FILE}")


if __name__ == "__main__":
    main()
