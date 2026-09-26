from datetime import datetime

from sqlalchemy import DateTime, Float, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class GridPrice(Base):
    """ERCOT settlement point price. RT intervals are 15 min, DA intervals are 1 hour."""

    __tablename__ = "grid_prices"

    settlement_point: Mapped[str] = mapped_column(String(20), primary_key=True)
    market: Mapped[str] = mapped_column(String(2), primary_key=True)  # "RT" or "DA"
    interval_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    price: Mapped[float] = mapped_column(Float)  # $/MWh


class GridZoneMetrics(Base):
    """Latest computed economics for one load zone (overwritten on each compute run)."""

    __tablename__ = "grid_zone_metrics"

    settlement_point: Mapped[str] = mapped_column(String(20), primary_key=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    grid_value_score: Mapped[float] = mapped_column(Float)
    metrics: Mapped[dict] = mapped_column(JSONB)  # raw driver values
    scores: Mapped[dict] = mapped_column(JSONB)  # 0-100 driver scores
    series: Mapped[dict] = mapped_column(JSONB)  # chart data for the detail page
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
