"""Pre-label the gold set with an LLM (300 permits only; never used on the full dataset).

Writes data/gold/labels_llm_<model>.csv in the same schema as the hand labels, plus the model's
confidence and a one-line reason. Hand labels (labels.csv) are never touched: review the
permits where LLM, Jev, and keywords disagree, and the hand label wins.

  uv run python -m permits.llm_label --model gpt-... [--effort high] [--limit 5]
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
from pathlib import Path
from typing import Literal

import pandas as pd
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from tqdm import tqdm

from permits.gold import GOLD, LABEL_COLS, SAMPLE
from permits.label import EQUIPMENT
from permits.questions import ACTION, PROPERTY, state

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def out_path(model: str) -> Path:
    return GOLD / f"labels_llm_{model}.csv"

Action = Literal[tuple(ACTION.criteria)]  # type: ignore[valid-type]
Property = Literal[tuple(PROPERTY.criteria)]  # type: ignore[valid-type]


class PermitLabel(BaseModel):
    standby_generator: bool
    portable_generator_hookup: bool
    battery: bool
    solar: bool
    panel_upgrade: bool
    ev_charger: bool
    action: Action
    property: Property
    confidence: Literal["high", "medium", "low"]
    reason: str = Field(description="One short sentence explaining the hardest call.")


def _defs(choice) -> str:
    return "\n".join(f"  - {k}: {v}" for k, v in choice.criteria.items())


GUIDE = f"""You label Texas city building permits (Austin, San Antonio) for a study of home backup
power adoption. Label only what the permit text supports. Each permit has: permit_type,
work_class, permit_class (Austin only: Residential/Commercial), description, contractor.

Equipment the permit concerns (true for every one that applies; all false is fine):
  - standby_generator: a permanently installed engine generator (Generac, Kohler, Cummins...).
    True also when the permit only runs a gas line, pad, or wiring for one. A transfer switch
    installed with a generator counts.
  - portable_generator_hookup: inlet box, interlock kit, or manual transfer switch for a portable generator.
  - battery: home/building battery energy storage (Powerwall, Enphase, FranklinWH incl. its
    gateway/backup switch, PWRcell, Base Power, SolarEdge, "ESS"). Not UPS units or vehicle batteries.
  - solar: solar PV panels. San Antonio files generators and batteries under the permit type
    "Solar - Photovoltaic Permit": the permit type alone does not make it solar.
  - panel_upgrade: main service or main panel upgrade/replacement ("100A to 200A", "heavy up").
  - ev_charger: EV charger or its circuit.
Names of people, streets, subdivisions, or companies that merely contain a word (Franklin,
Briggs, Battery Lane, Tesla Drive) do not count.

action, what the permit does to the main equipment:
{_defs(ACTION)}
If the description is only a name plus equipment ("McDaniel - Battery"), action is cant_tell.

property:
{_defs(PROPERTY)}
If the text doesn't say, use Austin's permit_class (Residential -> single_family_home,
Commercial -> commercial_or_public); otherwise cant_tell. Cell towers and telecom sites are commercial.
"""


async def _label_all(rows: list[dict], model: str, effort: str | None, concurrency: int) -> dict[str, dict]:
    client = AsyncOpenAI()
    sem = asyncio.Semaphore(concurrency)
    out: dict[str, dict] = {}
    extra = {"reasoning": {"effort": effort}} if effort else {}

    async def one(r: dict):
        async with sem:
            resp = await client.responses.parse(
                model=model, instructions=GUIDE, input=json.dumps(state(r)), text_format=PermitLabel, **extra,
            )
        lab = resp.output_parsed
        rec = {"gold_id": r["gold_id"], **{k: "1" if getattr(lab, k) else "0" for k in EQUIPMENT},
               "action": lab.action, "property": lab.property, "notes": "",
               "llm_confidence": lab.confidence, "llm_reason": lab.reason}
        out[r["gold_id"]] = rec
        bar.update()

    with tqdm(total=len(rows), desc=model) as bar:
        await asyncio.gather(*(one(r) for r in rows))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get("OPENAI_MODEL"))
    ap.add_argument("--effort", help="reasoning effort, e.g. high")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()
    if not args.model:
        ap.error("set --model or OPENAI_MODEL in ml/.env")

    OUT = out_path(args.model)
    g = pd.read_csv(SAMPLE, dtype=str)
    done = pd.read_csv(OUT, dtype=str) if OUT.exists() else pd.DataFrame(columns=["gold_id"])
    todo = g[~g.gold_id.isin(done.gold_id)]
    if args.limit:
        todo = todo.head(args.limit)
    rows = [{k: (None if pd.isna(v) else v) for k, v in r.items()} for r in todo.to_dict("records")]
    print(f"{len(rows)} permits to label ({len(done)} already in {OUT.name})")
    new = asyncio.run(_label_all(rows, args.model, args.effort, args.concurrency))

    cols = LABEL_COLS + ["llm_confidence", "llm_reason"]
    merged = pd.concat([done, pd.DataFrame(new.values())], ignore_index=True)[cols]
    merged.sort_values("gold_id").to_csv(OUT, index=False, quoting=csv.QUOTE_MINIMAL)
    print(f"wrote {len(merged)} rows to {OUT}")
    print(merged.llm_confidence.value_counts().to_string())


if __name__ == "__main__":
    main()
