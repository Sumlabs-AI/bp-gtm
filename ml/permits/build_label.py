"""Label v1: Jev answers -> per-permit install events -> deduped -> 2020 block groups.

  uv run python -m permits.build_label

Inputs:  data/interim/permits_jev.parquet (permits.jev over permits_all.parquet)
         data/raw/tiger/tl_2020_48_{bg,place}.zip
Outputs: data/processed/permit_events.parquet  one row per install event (after dedup)
         data/processed/bg_permits.parquet     block group x year x category counts
         data/processed/bg_city_share.parquet  share of each block group's land inside the permit city
"""
from __future__ import annotations

import re
from pathlib import Path

import geopandas as gpd
import pandas as pd

from permits.label import ADOPTION_ACTIONS, backup_install, jev_fields, keyword_fields

ROOT = Path(__file__).resolve().parents[1]
INTERIM, PROCESSED, TIGER = ROOT / "data" / "interim", ROOT / "data" / "processed", ROOT / "data" / "raw" / "tiger"

DEDUP_DAYS = 180
# Answers this close to the Noul cutoff are flagged; the label is reported with and without them.
UNCERTAIN_BAND = (0.3, 0.7)
NOT_BUILT = {"Expired", "Withdrawn", "VOID", "Void", "Cancelled - Contractor Required", "Aborted"}
CITY_PLACES = {"austin": "Austin", "san_antonio": "San Antonio", "fort_worth": "Fort Worth"}
# Fort Worth publishes descriptions on building permits only (generators are on blank trade permits):
# its backup_install is effectively a battery label. Compare it with battery_install elsewhere.


def _norm_address(city: pd.Series, addr: pd.Series) -> pd.Series:
    a = addr.fillna("").str.upper().str.replace(r",\s*CITY OF .*$", "", regex=True)
    a = a.map(lambda s: re.sub(r"[^A-Z0-9 ]", " ", s)).str.replace(r"\s+", " ", regex=True).str.strip()
    return city + "|" + a


def events(df: pd.DataFrame) -> pd.DataFrame:
    f = jev_fields(df)
    kw = keyword_fields(df)
    adoption = f["action"].isin(ADOPTION_ACTIONS)
    residential = f["property"].isin({"single_family_home", "cant_tell"})
    base_power = (df["contractor"].fillna("") + " " + df["description"].fillna("")).str.contains("BASE POWER", case=False)

    out = df[["city", "permit_id", "permit_type", "work_class", "description", "contractor", "address",
              "lat", "lon", "status", "source_row_kind"]].copy()
    out["date"] = df["issued_date"].fillna(df["applied_date"])
    out["year"] = out["date"].dt.year
    out["gen_install"] = f["standby_generator"] & adoption & residential
    out["battery_install"] = f["battery"] & adoption & residential
    out["backup_install"] = backup_install(f)
    out["solar_install"] = f["solar"] & adoption & residential
    out["panel_upgrade"] = f["panel_upgrade"] & residential & ~f["action"].isin({"remove", "revision"})
    out["ev_charger"] = f["ev_charger"] & adoption & residential
    out["backup_install_kw"] = backup_install(kw)  # label v0, for comparison
    out["base_power"] = base_power
    out["not_built"] = df["status"].isin(NOT_BUILT)
    lo, hi = UNCERTAIN_BAND
    near = lambda p: p.between(lo, hi)
    touches_backup = f["standby_generator"] | f["battery"] | kw["standby_generator"] | kw["battery"]
    out["uncertain"] = touches_backup & (
        near(df["p_standby_generator"]) | near(df["p_battery"]) | (df["action_conf"] < 0.5)
    )
    out["addr_key"] = _norm_address(df["city"], df["address"])
    return out


CATEGORIES = ["gen_install", "battery_install", "backup_install", "solar_install", "panel_upgrade", "ev_charger"]


def dedup(ev: pd.DataFrame, col: str) -> pd.Series:
    """True for the first event of `col` at an address; repeats within DEDUP_DAYS are dropped."""
    keep = pd.Series(False, index=ev.index)
    has_addr = ~ev["addr_key"].str.endswith("|")
    # Same-address, same-day ties: keep the built permit, then the lowest id, so the result is deterministic.
    sub = ev[ev[col] & has_addr].sort_values(["date", "not_built", "permit_id"], kind="stable")
    last: dict[str, pd.Timestamp] = {}
    for i, k, d in zip(sub.index, sub["addr_key"], sub["date"]):
        if k not in last or (d - last[k]).days > DEDUP_DAYS:
            keep[i] = True
            last[k] = d
    no_addr = ev[col] & ~has_addr
    return keep | no_addr


def block_groups() -> gpd.GeoDataFrame:
    return gpd.read_file(f"zip://{TIGER / 'tl_2020_48_bg.zip'}")[["GEOID", "ALAND", "geometry"]]


def city_share(bg: gpd.GeoDataFrame) -> pd.DataFrame:
    places = gpd.read_file(f"zip://{TIGER / 'tl_2020_48_place.zip'}")
    places = places[places["NAME"].isin(CITY_PLACES.values())].to_crs(bg.crs)
    rows = []
    for city, name in CITY_PLACES.items():
        poly = places[places["NAME"] == name].geometry.union_all()
        cand = bg[bg.intersects(poly)]
        eq = cand.to_crs(5070)  # equal-area for shares
        inside = eq.intersection(gpd.GeoSeries([poly], crs=bg.crs).to_crs(5070).iloc[0]).area
        rows.append(pd.DataFrame({"GEOID": cand["GEOID"].values, "city": city,
                                  "share_in_city": (inside / eq.area).values}))
    return pd.concat(rows, ignore_index=True)


def main():
    df = pd.read_parquet(INTERIM / "permits_jev.parquet")
    df = df[df["source_row_kind"] == "candidate"]  # recall-sample rows exist only to measure recall
    ev = events(df)
    for c in CATEGORIES + ["backup_install_kw"]:
        ev[c] = ev[c] & dedup(ev, c)

    bg = block_groups()
    pts = gpd.GeoDataFrame(ev, geometry=gpd.points_from_xy(ev["lon"], ev["lat"]), crs=4326).to_crs(bg.crs)
    ev = gpd.sjoin(pts, bg[["GEOID", "geometry"]], how="left", predicate="within").drop(columns=["geometry", "index_right"])
    ev = pd.DataFrame(ev)

    PROCESSED.mkdir(parents=True, exist_ok=True)
    cols = CATEGORIES + ["backup_install_kw"]
    ev = ev[ev[cols].any(axis=1)]
    ev.to_parquet(PROCESSED / "permit_events.parquet", index=False)

    built = ev[~ev["not_built"] & ~ev["base_power"] & ev["GEOID"].notna()]
    counts = built.groupby(["GEOID", "city", "year"])[cols].sum().reset_index()
    intent = ev[ev["not_built"] & ev["GEOID"].notna()].groupby(["GEOID", "city", "year"])["backup_install"].sum()
    counts = counts.merge(intent.rename("backup_not_built").reset_index(), how="outer", on=["GEOID", "city", "year"]).fillna(0)
    bp = ev[ev["base_power"] & ev["GEOID"].notna()].groupby(["GEOID", "city", "year"]).size()
    counts = counts.merge(bp.rename("base_power").reset_index(), how="outer", on=["GEOID", "city", "year"]).fillna(0)
    counts.to_parquet(PROCESSED / "bg_permits.parquet", index=False)
    city_share(bg).to_parquet(PROCESSED / "bg_city_share.parquet", index=False)

    print(f"{len(ev):,} events; {ev['GEOID'].isna().mean():.1%} without a block group (no coordinates)")
    print(built.groupby(["city", "year"])[["backup_install", "gen_install", "battery_install", "backup_install_kw"]].sum()
          .astype(int).to_string())
    print("uncertain share of backup installs:", f"{ev.loc[ev.backup_install, 'uncertain'].mean():.1%}")
    print("not built (expired/withdrawn/void) backup:", int(ev.loc[ev.not_built, "backup_install"].sum()),
          "| Base Power events:", int(ev["base_power"].sum()))


if __name__ == "__main__":
    main()
