"""Weather features in Postgres: replaced wholesale on each compute, read per Cell."""

from datetime import datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CountyTemperatureFeatures, StormFeatures
from app.need.components import replace_rows


def save_storm_features(db: Session, df: pd.DataFrame, now: datetime) -> int:
    return replace_rows(db, StormFeatures, df, now)


def save_county_temperature(db: Session, df: pd.DataFrame, now: datetime) -> int:
    return replace_rows(db, CountyTemperatureFeatures, df, now)


def load_features(
    db: Session, res6_cells: set[str], county_fips: set[str]
) -> tuple[dict[str, StormFeatures], dict[str, CountyTemperatureFeatures]]:
    storms = db.scalars(select(StormFeatures).where(StormFeatures.h3_index.in_(res6_cells)))
    temps = db.scalars(
        select(CountyTemperatureFeatures).where(
            CountyTemperatureFeatures.county_fips.in_(county_fips)
        )
    )
    return {s.h3_index: s for s in storms}, {t.county_fips: t for t in temps}
