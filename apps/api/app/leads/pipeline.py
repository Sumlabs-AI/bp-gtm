"""Refresh lead data sources and log every attempt in source_runs.

For each source: fingerprint() → skip if unchanged since the last successful run →
fetch() raw files into data/raw/<source>/<timestamp>/ (kept: some upstream files expire)
→ parse() → quality gate → load → record the run.
"""

import importlib
import traceback
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

from sqlalchemy import select

from app.db import SessionLocal
from app.leads.store import LOADERS
from app.models import SourceRun

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"

# source id -> (adapter module, loader kind)
SOURCES: dict[str, tuple[str, str]] = {
    "hcad": ("app.leads.adapters.hcad", "property"),
    "hcad_parcels": ("app.leads.adapters.hcad_parcels", "location"),  # after hcad
    "ercot_esiid": ("app.leads.adapters.ercot_esiid", "meter"),
    "harris_permits": ("app.leads.adapters.harris_permits", "permit"),
    "houston_permits": ("app.leads.adapters.houston_permits", "permit"),
}

# Refuse to load a refresh that shrinks a source by more than this share: it usually means
# a truncated download or a changed file format, and loading it would drop real leads.
MAX_SHRINK = 0.4


def adapter(source_id: str) -> ModuleType:
    return importlib.import_module(SOURCES[source_id][0])


def last_success(db, source_id: str) -> SourceRun | None:
    return db.scalar(
        select(SourceRun)
        .where(SourceRun.source_id == source_id, SourceRun.status == "success")
        .order_by(SourceRun.started_at.desc(), SourceRun.id.desc())
        .limit(1)
    )


def run_source(
    source_id: str,
    *,
    force: bool = False,
    now: datetime | None = None,
    module: ModuleType | None = None,
) -> SourceRun:
    """Refresh one source. `module` overrides the adapter (used by tests)."""
    now = now or datetime.now(UTC)
    mod = module or adapter(source_id)
    kind = SOURCES[source_id][1]
    with SessionLocal() as db:
        run = SourceRun(source_id=source_id, started_at=now, status="running")
        db.add(run)
        db.commit()
        try:
            previous = last_success(db, source_id)
            run.fingerprint = mod.fingerprint()
            if previous and previous.fingerprint == run.fingerprint and not force:
                run.status = "skipped"
            else:
                raw_dir = RAW_DIR / source_id / now.strftime("%Y%m%dT%H%M%SZ")
                raw_dir.mkdir(parents=True, exist_ok=True)
                run.raw_path = str(raw_dir)
                df = mod.parse(mod.fetch(raw_dir))
                run.rows = len(df)
                if previous and previous.rows and len(df) < previous.rows * (1 - MAX_SHRINK):
                    raise ValueError(
                        f"quality gate: {len(df):,} rows vs {previous.rows:,} last time"
                    )
                run.inserted, run.updated = LOADERS[kind](df, now)
                run.status = "success"
        except Exception:
            run.status = "failed"
            run.error = traceback.format_exc(limit=5)
        run.finished_at = datetime.now(UTC)
        db.commit()
        db.refresh(run)
        return run
