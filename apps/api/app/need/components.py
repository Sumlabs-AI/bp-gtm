"""What every Need Component shares: sub-scores combine as the mean of those that exist,
and feature tables are replaced wholesale on each compute."""

from datetime import datetime

import pandas as pd
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from app.db import Base


def mean_of_present(*scores: float | None) -> float | None:
    """Placeholder equal-weight blend of the sub-scores that exist; None when none do."""
    present = [s for s in scores if s is not None]
    return round(sum(present) / len(present), 1) if present else None


def replace_rows(db: Session, model: type[Base], df: pd.DataFrame, now: datetime) -> int:
    """Replace every row of a feature table; `computed_at` is stamped with `now`."""
    db.execute(delete(model))
    if df.empty:
        return 0
    columns = [c.name for c in model.__table__.columns if c.name != "computed_at"]
    rows = df[columns].astype(object).where(df[columns].notna(), None).to_dict("records")
    db.execute(insert(model), [{**r, "computed_at": now} for r in rows])
    return len(rows)
