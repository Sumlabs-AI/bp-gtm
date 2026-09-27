"""Run the Jev questions over permits, with an on-disk answer cache.

Identical states are asked once: the cache key is (QUESTIONS_VERSION, model, state), so
re-running after a crash or on overlapping sets costs nothing. TYPESAFE_API_KEY comes from
ml/.env (see .env.example).

  uv run python -m permits.jev --input data/gold/gold.csv --limit 5
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from tqdm import tqdm
from typesafe_sdk import AsyncTypeSafeClient, TypeSafeClient

from permits.questions import QUESTIONS_VERSION, questions, state

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

MODEL = "jev-1.13.0"  # pinned: answers are cached per model
CACHE = ROOT / "data" / "interim" / "jev_cache.jsonl"


def client() -> TypeSafeClient:
    return TypeSafeClient(model=MODEL)


def async_client() -> AsyncTypeSafeClient:
    return AsyncTypeSafeClient(model=MODEL)


def cache_key(st: dict) -> str:
    blob = json.dumps([QUESTIONS_VERSION, MODEL, st], sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()


def _load_cache() -> dict[str, dict]:
    if not CACHE.exists():
        return {}
    with CACHE.open() as f:
        return {(r := json.loads(line))["key"]: r for line in f}


def _flatten(resp) -> dict:
    out = {}
    for qid, a in resp.nouls.items():
        out[f"p_{qid}"] = a.noul
    for qid, a in resp.choices.items():
        out[qid] = a.choice
        out[f"{qid}_conf"] = a.confidence
        out.update({f"p_{qid}__{k}": v for k, v in a.probabilities.items()})
    return out


async def _ask_all(states: dict[str, dict], concurrency: int) -> None:
    qs = questions()
    sem = asyncio.Semaphore(concurrency)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    async with async_client() as c:
        with CACHE.open("a") as f, tqdm(total=len(states), desc="jev") as bar:
            async def one(key: str, st: dict):
                async with sem:
                    resp = await c.system_one(st, qs)
                rec = {"key": key, "version": QUESTIONS_VERSION, "model": MODEL,
                       "request_id": resp.request_id, **_flatten(resp)}
                f.write(json.dumps(rec) + "\n")
                f.flush()
                bar.update()

            await asyncio.gather(*(one(k, s) for k, s in states.items()))


def run(df: pd.DataFrame, concurrency: int = 16) -> pd.DataFrame:
    """Return df with Jev answer columns joined on. Only uncached states hit the API."""
    states = [state(r) for r in df.to_dict("records")]
    keys = [cache_key(s) for s in states]
    cached = _load_cache()
    todo = {k: s for k, s in zip(keys, states) if k not in cached}
    if todo:
        print(f"jev: {len(todo):,} new requests ({len(keys) - len(todo):,} cached)")
        asyncio.run(_ask_all(todo, concurrency))
        cached = _load_cache()
    ans = pd.DataFrame([cached[k] for k in keys], index=df.index).drop(columns=["key"])
    return df.join(ans)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="csv or parquet with permit columns")
    ap.add_argument("--output")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--concurrency", type=int, default=16)
    args = ap.parse_args()
    path = Path(args.input)
    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path, dtype=str)
    if args.limit:
        df = df.head(args.limit)
    out = run(df, args.concurrency)
    if args.output:
        out.to_parquet(args.output, index=False)
    else:
        cols = ["description"] + [c for c in out.columns if c.startswith("p_") and "__" not in c] + ["action", "property"]
        with pd.option_context("display.width", 250, "display.max_colwidth", 60, "display.float_format", "{:.2f}".format):
            print(out[cols].to_string(index=False))


if __name__ == "__main__":
    main()
