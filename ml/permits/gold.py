"""Gold set: ~300 hand-labeled permits for measuring keyword vs Jev accuracy.

  uv run python -m permits.gold sample   # writes data/gold/gold.csv (stratified, 50/50 tune/test)
  uv run python -m permits.gold serve    # labeling page on http://localhost:8765
                                         # review mode: http://localhost:8765/?review=1

Review mode shows only data/gold/review.csv (permits where LLM, Jev, and keywords disagree),
pre-filled with the LLM's answer. Final gold = LLM labels overridden by hand labels.

Labels are written to data/gold/labels.csv after every permit, so the page can be closed
and resumed. Strata are over-weighted toward rare and tricky cases; accuracy is reported
per stratum as well as overall.
"""
from __future__ import annotations

import argparse
import csv
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pandas as pd

from permits.label import EQUIPMENT

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data" / "gold"
SAMPLE = GOLD / "gold.csv"
LABELS = GOLD / "labels.csv"          # hand labels (win over the LLM)
LLM_LABELS = GOLD / "labels_llm_gpt-6-astra.csv"  # permits/llm_label.py (luna kept for agreement)
REVIEW = GOLD / "review.csv"
SEED = 7

EDGE_RE = (r"GAS LINE|DETACH|REINSTALL|REMOV|RELOCAT|INTERLOCK|INLET|PORTABLE|REVISION|APARTMENT"
           r"|COMMERCIAL|AT&T|\bSBA\b|TOWER|CHURCH|SCHOOL|UPS\b|REPAIR|REPLAC")

# (name, n, filter) applied to unique permits; earlier strata take rows first.
def _strata(d: pd.DataFrame) -> list[tuple[str, int, pd.Series]]:
    au, sa = d.city == "austin", d.city == "san_antonio"
    cand, rec = d.source_row_kind == "candidate", d.source_row_kind == "recall_sample"
    up = d.description.fillna("").str.upper()
    edge = up.str.contains(EDGE_RE, regex=True)
    return [
        ("edge_cases", 50, cand & edge & (d.kw_generator | d.kw_battery | d.kw_solar)),
        ("austin_generator", 30, au & cand & d.kw_generator),
        ("austin_battery", 30, au & cand & d.kw_battery),
        ("austin_solar", 15, au & cand & d.kw_solar),
        ("austin_panel", 15, au & cand & d.kw_panel),
        ("austin_contractor", 10, au & cand & d.kw_contractor),
        ("sa_generator", 30, sa & cand & d.kw_generator),
        ("sa_battery", 25, sa & cand & d.kw_battery),
        ("sa_solar", 15, sa & cand & d.kw_solar),
        ("sa_other", 10, sa & cand),
        ("recall_austin", 35, au & rec),
        ("recall_sa", 35, sa & rec),
    ]


def sample() -> pd.DataFrame:
    df = pd.read_parquet(ROOT / "data" / "interim" / "permits_all.parquet")
    # One row per distinct text: identical permits would leak between tune and test halves.
    d = df.drop_duplicates(["city", "permit_type", "work_class", "description", "contractor"]).reset_index(drop=True)
    rng = np.random.default_rng(SEED)
    taken = pd.Series(False, index=d.index)
    parts = []
    for name, n, mask in _strata(d):
        pool = d.index[mask & ~taken]
        pick = rng.choice(pool, size=min(n, len(pool)), replace=False)
        taken[pick] = True
        parts.append(d.loc[pick].assign(stratum=name))
    g = pd.concat(parts)
    g = g.sample(frac=1, random_state=SEED).reset_index(drop=True)  # labeling order
    g["split"] = np.where(rng.random(len(g)) < 0.5, "tune", "test")
    g["gold_id"] = [f"g{i:03d}" for i in range(len(g))]
    cols = ["gold_id", "split", "stratum", "city", "permit_id", "permit_type", "work_class", "class_hint",
            "description", "contractor", "status", "issued_date", "source_row_kind"]
    GOLD.mkdir(parents=True, exist_ok=True)
    g[cols].to_csv(SAMPLE, index=False)
    print(f"wrote {len(g)} rows to {SAMPLE}")
    print(g.stratum.value_counts().to_string())
    return g[cols]


# ------------------------------------------------------------------ labeling page
LABEL_COLS = ["gold_id", *EQUIPMENT, "action", "property", "notes"]


def _read_labels() -> dict[str, dict]:
    if not LABELS.exists():
        return {}
    with LABELS.open() as f:
        return {r["gold_id"]: r for r in csv.DictReader(f)}


def final_labels() -> pd.DataFrame:
    """LLM labels with every override (hand review or adjudication) replacing the LLM label."""
    llm = pd.read_csv(LLM_LABELS, dtype=str).fillna("")
    hand = pd.read_csv(LABELS, dtype=str).fillna("") if LABELS.exists() else llm.iloc[:0]
    hand = hand.assign(source="override")
    return pd.concat([hand, llm[~llm.gold_id.isin(hand.gold_id)].assign(source="llm")], ignore_index=True)


def _write_labels(labels: dict[str, dict]) -> None:
    tmp = LABELS.with_suffix(".tmp")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, LABEL_COLS)
        w.writeheader()
        for r in labels.values():
            w.writerow({k: r.get(k, "") for k in LABEL_COLS})
    tmp.replace(LABELS)


PAGE = (Path(__file__).parent / "gold_page.html")


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, ctype: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/":
            self._send(PAGE.read_bytes(), "text/html; charset=utf-8")
        elif self.path in ("/data", "/data?review=1"):
            rows = pd.read_csv(SAMPLE, dtype=str).fillna("")
            suggest = {}
            if self.path.endswith("review=1"):
                review = pd.read_csv(REVIEW, dtype=str)
                rows = rows.merge(review, on="gold_id")
                llm = pd.read_csv(LLM_LABELS, dtype=str).fillna("")
                suggest = {r["gold_id"]: r for r in llm[llm.gold_id.isin(review.gold_id)].to_dict("records")}
            body = {"rows": rows.to_dict("records"), "labels": _read_labels(), "suggest": suggest}
            self._send(json.dumps(body).encode(), "application/json")
        else:
            self._send(b"not found", "text/plain", 404)

    def do_POST(self):
        if self.path != "/label":
            return self._send(b"not found", "text/plain", 404)
        rec = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        labels = _read_labels()
        labels[rec["gold_id"]] = rec
        _write_labels(labels)
        self._send(json.dumps({"saved": len(labels)}).encode(), "application/json")

    def log_message(self, *args):
        pass


def serve(port: int) -> None:
    if not SAMPLE.exists():
        sample()
    print(f"labeling page: http://localhost:{port}  (labels -> {LABELS})")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sample", "serve"])
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    sample() if args.cmd == "sample" else serve(args.port)


if __name__ == "__main__":
    main()
