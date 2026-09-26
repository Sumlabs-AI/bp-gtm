"""ACS step 1: download the ACS 5-year tables and keep Texas block groups + tracts.

  uv run python -m acs.fetch [--vintage 2024] [--force]

Streams each national table-based summary file and keeps only the header and Texas block-group /
tract rows, so the cache stays small.

Outputs: data/raw/acs/<vintage>/<table>.dat           Texas rows of each table (cache; delete to refetch)
         data/raw/acs/<vintage>/table_shells.txt      line labels, for the data dictionary
         data/interim/acs_<vintage>_{bg,tract}.parquet  one row per GEOID, columns B25003_E001 / B25003_M001 ...
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from acs.variables import GEO_PREFIX, SENTINEL_MAX, SF_URL, SHELLS_URL, TABLES

ROOT = Path(__file__).resolve().parents[1]
RAW, INTERIM = ROOT / "data" / "raw" / "acs", ROOT / "data" / "interim"


def _download_table(vintage: int, table: str, out: Path) -> None:
    keep = tuple(GEO_PREFIX.values())
    tmp = out.with_suffix(".part")
    with requests.get(SF_URL.format(vintage=vintage, table=table.lower()), stream=True, timeout=600) as r:
        r.raise_for_status()
        r.encoding = "utf-8"  # not declared by the server; iter_lines would yield bytes
        with tmp.open("w") as f:
            lines = r.iter_lines(decode_unicode=True)
            f.write(next(lines) + "\n")  # header
            for line in lines:
                if line.startswith(keep):
                    f.write(line + "\n")
    tmp.rename(out)


def shell_labels(vintage: int, force: bool = False) -> pd.Series:
    """Line labels of every table (index B25038_003 ...), cached in data/raw/acs/<vintage>/."""
    path = RAW / str(vintage) / "table_shells.txt"
    if force or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(SHELLS_URL.format(vintage=vintage), timeout=300)
        r.raise_for_status()
        path.write_bytes(r.content)
    s = pd.read_csv(path, sep="|", dtype=str).dropna(subset=["Unique ID"])
    return s.drop_duplicates("Unique ID").set_index("Unique ID")["Label"].str.strip()


def download(vintage: int, force: bool = False) -> Path:
    d = RAW / str(vintage)
    d.mkdir(parents=True, exist_ok=True)
    shell_labels(vintage, force)
    todo = [t for t in TABLES if force or not (d / f"{t}.dat").exists()]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for t, _ in zip(todo, pool.map(lambda t: _download_table(vintage, t, d / f"{t}.dat"), todo)):
            print(f"  {t} downloaded")
    print(f"{len(TABLES) - len(todo)} tables cached, {len(todo)} downloaded -> {d}")
    return d


def _read_table(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep="|", dtype={"GEO_ID": str}).set_index("GEO_ID")
    df = df.apply(pd.to_numeric, errors="coerce")
    est = [c for c in df.columns if "_E" in c]
    df[est] = df[est].mask(df[est] <= SENTINEL_MAX)  # annotation codes -> NaN; MOE codes kept for features
    return df


def build_interim(vintage: int, d: Path) -> None:
    wide = pd.concat([_read_table(d / f"{t}.dat") for t in TABLES], axis=1)
    for geo, prefix in GEO_PREFIX.items():
        part = wide[wide.index.str.startswith(prefix)].copy()
        part.index = part.index.str.split("US").str[1]  # 1500000US480019501001 -> 480019501001
        part.index.name = "GEOID"
        part = part.astype(np.float64).reset_index()
        out = INTERIM / f"acs_{vintage}_{geo}.parquet"
        part.to_parquet(out, index=False)
        print(f"{geo}: {len(part):,} rows x {part.shape[1] - 1} columns -> {out.relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vintage", type=int, default=2024, help="ACS 5-year end year (2024 = 2020-2024)")
    ap.add_argument("--force", action="store_true", help="re-download cached tables")
    args = ap.parse_args()
    build_interim(args.vintage, download(args.vintage, args.force))


if __name__ == "__main__":
    main()
