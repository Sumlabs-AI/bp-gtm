"""Step 2: map each county's raw parcels to one schema and classify home type.

  uv run python -m parcels.normalize                # all counties with a raw file
  uv run python -m parcels.normalize --counties dallas

Input:  data/interim/parcels_raw_{county}.parquet   (parcels.fetch: Travis, Bexar county services)
        data/raw/parcels/tarrant_tad/ParcelView.zip   (Tarrant Appraisal District, tad.org/resources/data-downloads:
          polygons + 2026 appraisal, living area, pool; StratMap's Tarrant file has no values)
        data/raw/parcels/stratmap25-landparcels_{fips}_lp.zip   (TxGIO statewide schema, DFW counties;
          downloaded by hand in a browser - the CDN blocks scripted downloads)
Output: data/interim/parcels_{county}.parquet       one row per parcel, canonical columns below

Canonical columns:
  county, prop_id, state_cd, home_type, living_sqft, year_built, stories, lot_sqft,
  market_value, homestead, deed_year, geometry (EPSG:4326)
type_source: where home_type comes from - "state_code" (PTAD code), "local_code" (a county's own code,
e.g. Williamson RES), or "value_rule" (no code at all, see VALUE_RULE).
Missing in a county -> NaN (Travis has no living sq ft, Bexar no deed year, StratMap counties have
neither sq ft nor deed year, and Dallas' StratMap file has no year built).
homestead = owner-occupied: Bexar's HS exemption code; elsewhere mailing address = property address.
State codes are cut to the PTAD category (first code, 2 chars): Dallas "A11" -> A1, Denton
"A1,A1" -> A1; Tarrant's state field holds only the letter, so its local code is used.

home_type from the Texas PTAD state property category (same codes in every appraisal district):
  A1/E1 single-family (E1 = farm/ranch home) -> sfr_detached, or sfr_attached when the lot is
  under ATTACHED_LOT_SQFT (townhomes are coded A1 too; a small lot is the only public tell)
  A2, M*  mobile        A4  condo        B*  multifamily        C*  vacant
  A3/A5 "details" rows and everything else -> other

Many StratMap counties publish no land-use code at all (Comal, Ellis, Fort Bend, Galveston, Hays, Johnson,
Montgomery, Parker, Rockwall; others only partly). There, a parcel counts as single-family when it has a house
worth something on a house-sized lot and isn't a condo (VALUE_RULE). Checked against real codes on 60k parcels:
Collin precision 96% / recall 96%, Denton 90% / 93%. Williamson has no improvement values but codes RES.
"""
from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
RAW = ROOT / "data" / "raw" / "parcels"

STRATMAP = {
    # DFW
    "dallas": "48113", "collin": "48085", "denton": "48121", "rockwall": "48397",
    "kaufman": "48257", "ellis": "48139", "johnson": "48251", "parker": "48367",
    # Austin
    "williamson": "48491", "hays": "48209", "bastrop": "48021",
    # San Antonio
    "comal": "48091", "guadalupe": "48187", "kendall": "48259",
    # Houston
    "harris": "48201", "fort_bend": "48157", "montgomery": "48339", "brazoria": "48039", "galveston": "48167",
}
STRATMAP_COLUMNS = ["Prop_ID", "STAT_LAND_", "LOC_LAND_U", "YEAR_BUILT", "MKT_VALUE", "IMP_VALUE", "LEGAL_DESC",
                    "SITUS_ADDR", "MAIL_ADDR"]
STATE_CODE = r"^[A-FJLMOSX][0-9]$"  # PTAD category shape: letter + digit
LOCAL_RESIDENTIAL = {"williamson": {"RES"}}
VALUE_RULE = {"min_imp_value": 30_000, "min_market_value": 50_000, "lot_sqft": (3_000, 87_120)}  # 87,120 = 2 acres
CONDO = r"CONDO|\bUNIT\b|\bAPT|TOWNHOME|\bTH\b"
DIRECTIONALS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}

ATTACHED_LOT_SQFT = 3_000  # below this a single-family lot is almost always a townhome / zero-lot-line
EQUAL_AREA = 5070
SQFT_PER_M2 = 10.7639
COLUMNS = ["county", "prop_id", "state_cd", "type_source", "home_type", "living_sqft", "year_built", "stories", "lot_sqft",
           "market_value", "homestead", "deed_year", "pool", "geometry"]


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _year(s: pd.Series) -> pd.Series:
    y = _num(s)
    return y.where(y.between(1800, 2026))


def home_type(state_cd: pd.Series, lot_sqft: pd.Series) -> pd.Series:
    cd = state_cd.fillna("").str.upper().str.strip()
    sfr = cd.str.match(r"^(A1|E1)")
    out = np.select(
        [sfr & (lot_sqft < ATTACHED_LOT_SQFT), sfr, cd.str.match(r"^(A2|M)"), cd.str.startswith("A4"),
         cd.str.startswith("B"), cd.str.startswith("C")],
        ["sfr_attached", "sfr_detached", "mobile", "condo", "multifamily", "vacant"],
        default="other",
    )
    return pd.Series(out, index=state_cd.index)


def _owner_occupied(situs_num: pd.Series, situs_street: pd.Series, mail: pd.Series) -> pd.Series:
    """Mailing address contains the property's house number and first street word."""
    up = lambda s: s.fillna("").astype(str).str.upper().str.strip()
    num, street, mail = up(situs_num), up(situs_street).str.split().str[0].fillna(""), up(mail)
    return pd.Series([bool(n and s) and re.search(rf"\b{re.escape(n)}\b", m) is not None and s in m
                      for n, s, m in zip(num, street, mail)], index=mail.index)


def _situs_parts(addr: pd.Series) -> tuple[pd.Series, pd.Series]:
    """House number and first non-directional street word from a one-line situs address."""
    tokens = addr.fillna("").astype(str).str.upper().str.split(",").str[0].str.split()
    num = tokens.map(lambda t: t[0] if t and t[0][0].isdigit() else "")
    street = tokens.map(lambda t: next((w for w in t[1:] if w not in DIRECTIONALS), ""))
    return num, street


def _code2(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.split(",").str[0].str.strip().str.upper().str[:2]


def stratmap(g: gpd.GeoDataFrame, county: str) -> pd.DataFrame:
    stat, loc = _code2(g["STAT_LAND_"]), _code2(g["LOC_LAND_U"])
    code = stat.where(stat.str.match(STATE_CODE), loc.where(loc.str.match(STATE_CODE), ""))
    source = pd.Series(np.where(code != "", "state_code", ""), index=g.index)

    lot = g.geometry.to_crs(EQUAL_AREA).area * SQFT_PER_M2
    not_condo = ~g["LEGAL_DESC"].fillna("").str.upper().str.contains(CONDO)
    uncoded = code == ""
    if county in LOCAL_RESIDENTIAL:
        res = g["LOC_LAND_U"].fillna("").str.strip().str.upper().isin(LOCAL_RESIDENTIAL[county])
        hit = uncoded & res & not_condo & lot.between(*VALUE_RULE["lot_sqft"])
        code, source = code.mask(hit, "A1"), source.mask(uncoded, "local_code")
    else:
        r = VALUE_RULE
        hit = uncoded & (_num(g["IMP_VALUE"]) >= r["min_imp_value"]) & (_num(g["MKT_VALUE"]) >= r["min_market_value"]) \
            & lot.between(*r["lot_sqft"]) & not_condo
        code, source = code.mask(hit, "A1"), source.mask(uncoded, "value_rule")

    num, street = _situs_parts(g["SITUS_ADDR"])
    return pd.DataFrame({
        "prop_id": g["Prop_ID"].astype(str).str.strip(),
        "state_cd": code,
        "type_source": source,
        "living_sqft": np.nan,
        "year_built": _year(g["YEAR_BUILT"]),
        "stories": np.nan,
        "market_value": _num(g["MKT_VALUE"]),
        "homestead": _owner_occupied(num, street, g["MAIL_ADDR"]),
        "deed_year": np.nan,
    })


def travis(g: gpd.GeoDataFrame) -> pd.DataFrame:
    deed_year = _num(g["deed_num"].astype("string").str[:4])
    return pd.DataFrame({
        "prop_id": g["PROP_ID"].astype("Int64").astype(str),
        "state_cd": g["land_state_cd"],
        "living_sqft": np.nan,
        "year_built": _year(g["F1year_imprv"]),
        "stories": np.nan,
        "market_value": _num(g["market_value"]),
        # No exemption codes in this layer, and homesite value is set on ~96% of homes; the mailing
        # address matching the property (~82% of single-family) is the owner-occupancy proxy.
        "homestead": _owner_occupied(g["situs_num"], g["situs_street"], g["py_address"]),
        "deed_year": deed_year.where(deed_year.between(1950, 2026)),
    })


def bexar(g: gpd.GeoDataFrame) -> pd.DataFrame:
    sqft = _num(g["GBA"])
    return pd.DataFrame({
        "prop_id": g["PropID"].astype("Int64").astype(str),
        "state_cd": g["State_cd"],
        "living_sqft": sqft.where(sqft.between(200, 30_000)),
        "year_built": _year(g["YrBlt"]),
        "stories": _num(g["Stories"]),
        "market_value": _num(g["TotVal"]),
        "homestead": g["Exempts"].fillna("").str.contains(r"\bHS\b"),
        "deed_year": np.nan,
    })


def tarrant(g: gpd.GeoDataFrame) -> pd.DataFrame:
    deed = pd.to_datetime(g["Deed_Date"], errors="coerce").dt.year
    num, street = _situs_parts(g["Situs_Address"])
    return pd.DataFrame({
        "prop_id": g["Account_Num"].astype(str).str.strip(),
        # TAD class "A" = residential single-family (townhomes included; the lot-size rule splits them off)
        "state_cd": g["Property_Class"].fillna("").str.strip().replace({"A": "A1"}).str[:2],
        "living_sqft": _num(g["Living_Area"]).where(lambda x: x.between(200, 30_000)),
        "year_built": _year(g["Year_Built"]),
        "stories": np.nan,
        "market_value": _num(g["Total_Value"]),
        # No exemption codes in the public file: mailing address = property address, as for StratMap counties.
        "homestead": _owner_occupied(num, street, g["Owner_Address"]),
        "deed_year": deed.where(deed.between(1950, 2026)),
        "pool": g["Swimming_Pool_Ind"].eq("Y"),
    })


ADAPTERS = {"travis": travis, "bexar": bexar, "tarrant": tarrant}
TAD_ZIP = RAW / "tarrant_tad" / "ParcelView.zip"


def _stratmap_zip(county: str) -> Path:
    return RAW / f"stratmap25-landparcels_{STRATMAP[county]}_lp.zip"


def read_raw(county: str) -> gpd.GeoDataFrame:
    if county == "tarrant":
        g = gpd.read_file(f"zip://{TAD_ZIP}!ParcelView.gdb", engine="pyogrio")
        g = g[g["RP"] == "R"].drop_duplicates("Account_Num")  # real property, one row per account
        return g.to_crs(4326)
    if county in STRATMAP:
        z = _stratmap_zip(county)
        gdb = next(n for n in zipfile.ZipFile(z).namelist() if n.endswith(".gdb/")).rstrip("/")
        return gpd.read_file(f"zip://{z}!{gdb}", columns=STRATMAP_COLUMNS, engine="pyogrio").to_crs(4326)
    return gpd.read_parquet(INTERIM / f"parcels_raw_{county}.parquet")


def available() -> list[str]:
    return ([c for c in ADAPTERS if (INTERIM / f"parcels_raw_{c}.parquet").exists()
             or (c == "tarrant" and TAD_ZIP.exists())]
            + [c for c in STRATMAP if _stratmap_zip(c).exists()])


def normalize(county: str) -> Path:
    g = read_raw(county)
    df = stratmap(g, county) if county in STRATMAP else ADAPTERS[county](g)
    df["county"] = county
    if "type_source" not in df:
        df["type_source"] = "state_code"
    if "pool" not in df:  # only Tarrant publishes it so far
        df["pool"] = pd.NA
    df["lot_sqft"] = g.geometry.to_crs(EQUAL_AREA).area * SQFT_PER_M2
    df["home_type"] = home_type(df["state_cd"], df["lot_sqft"])
    out = gpd.GeoDataFrame(df, geometry=g.geometry.values, crs=g.crs)[COLUMNS]
    out = out[~(out.geometry.isna() | out.geometry.is_empty)]
    path = INTERIM / f"parcels_{county}.parquet"
    out.to_parquet(path)

    res = out[out["home_type"].str.startswith("sfr")]
    print(f"{county}: {len(out):,} parcels -> {path}")
    print("  home_type:", out["home_type"].value_counts().to_dict(),
          "| type_source:", out["type_source"].value_counts(normalize=True).round(2).to_dict())
    print("  single-family fill:", {c: f"{res[c].notna().mean():.0%}" for c in
                                    ["living_sqft", "year_built", "market_value", "deed_year"]},
          f"homestead {res['homestead'].mean():.0%}")
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--counties", nargs="+", default=available())
    for c in ap.parse_args().counties:
        normalize(c)


if __name__ == "__main__":
    main()
