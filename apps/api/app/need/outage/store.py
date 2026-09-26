"""Outage features in Postgres: replaced wholesale on each compute, read per Cell."""

from datetime import datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CountyOutageFeatures, UtilityReliability
from app.need.components import replace_rows


def save_county_features(db: Session, df: pd.DataFrame, now: datetime) -> int:
    return replace_rows(db, CountyOutageFeatures, df, now)


def save_utility_reliability(db: Session, df: pd.DataFrame, now: datetime) -> int:
    return replace_rows(db, UtilityReliability, df, now)


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
