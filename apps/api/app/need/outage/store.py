"""Outage features in Postgres: replaced wholesale on each compute, read per Cell."""

from datetime import datetime

import pandas as pd
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.models import CountyOutageFeatures, UtilityReliability


def _replace(
    db: Session,
    model: type[CountyOutageFeatures] | type[UtilityReliability],
    df: pd.DataFrame,
    now: datetime,
) -> int:
    """Replace every row of a feature table; `computed_at` is stamped with `now`."""
    columns = [c.name for c in model.__table__.columns if c.name != "computed_at"]
    rows = df[columns].astype(object).where(df[columns].notna(), None).to_dict("records")
    db.execute(delete(model))
    if rows:
        db.execute(insert(model), [{**r, "computed_at": now} for r in rows])
    return len(rows)


def save_county_features(db: Session, df: pd.DataFrame, now: datetime) -> int:
    return _replace(db, CountyOutageFeatures, df, now)


def save_utility_reliability(db: Session, df: pd.DataFrame, now: datetime) -> int:
    return _replace(db, UtilityReliability, df, now)


def load_features(
    db: Session, county_fips: set[str], utility_ids: set[int]
) -> tuple[dict[str, CountyOutageFeatures], dict[int, UtilityReliability]]:
    counties = db.scalars(
        select(CountyOutageFeatures).where(CountyOutageFeatures.county_fips.in_(county_fips))
    )
    utilities = db.scalars(
        select(UtilityReliability).where(UtilityReliability.utility_id.in_(utility_ids))
    )
    return {c.county_fips: c for c in counties}, {u.utility_id: u for u in utilities}
