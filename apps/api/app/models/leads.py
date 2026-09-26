from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Property(Base):
    """One appraisal account (county appraisal district record)."""

    __tablename__ = "properties"
    __table_args__ = (UniqueConstraint("county", "account"), Index(None, "lat", "lon"))

    id: Mapped[int] = mapped_column(primary_key=True)
    county: Mapped[str] = mapped_column(String(40))
    account: Mapped[str] = mapped_column(String(40))
    situs_address: Mapped[str | None] = mapped_column(Text)
    situs_city: Mapped[str | None] = mapped_column(Text)
    situs_zip: Mapped[str | None] = mapped_column(String(5))
    address_key: Mapped[str | None] = mapped_column(Text, index=True)
    owner_name: Mapped[str | None] = mapped_column(Text)
    mail_address: Mapped[str | None] = mapped_column(Text)
    state_class: Mapped[str | None] = mapped_column(String(10))
    is_single_family: Mapped[bool] = mapped_column(Boolean)
    homestead: Mapped[bool] = mapped_column(Boolean)
    confidential: Mapped[bool] = mapped_column(Boolean)
    market_value: Mapped[float | None] = mapped_column(Float)
    heated_sqft: Mapped[float | None] = mapped_column(Float)
    year_built: Mapped[int | None] = mapped_column(Integer)
    has_solar: Mapped[bool] = mapped_column(Boolean, server_default="false")
    has_pool: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # Point inside the parcel (WGS84), from the county parcel layer.
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Set when a later load sees a different owner: the "new owner" signal.
    owner_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Meter(Base):
    """One ERCOT ESI ID (electric service point)."""

    __tablename__ = "meters"

    esiid: Mapped[str] = mapped_column(String(40), primary_key=True)
    tdsp: Mapped[str] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    zip: Mapped[str | None] = mapped_column(String(5))
    county: Mapped[str | None] = mapped_column(String(40))
    address_key: Mapped[str | None] = mapped_column(Text, index=True)
    premise_type: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str | None] = mapped_column(String(40))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Permit(Base):
    """A solar / EV charger / new-home permit from a city or county feed."""

    __tablename__ = "permits"

    source: Mapped[str] = mapped_column(String(60), primary_key=True)
    permit_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    zip: Mapped[str | None] = mapped_column(String(5))
    address_key: Mapped[str | None] = mapped_column(Text, index=True)
    issued_date: Mapped[date | None] = mapped_column(Date)
    category: Mapped[str] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Lead(Base):
    """A scored, eligible property. Rebuilt by `python -m app.leads score`."""

    __tablename__ = "leads"

    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), primary_key=True
    )
    score: Mapped[float] = mapped_column(Float, index=True)
    drivers: Mapped[dict] = mapped_column(JSONB)  # driver key -> {score, value}
    signals: Mapped[list] = mapped_column(JSONB)  # evidence: [{type, date, detail, source}]
    reasons: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Latest "news" that makes this lead worth a fresh look, e.g. a new solar permit.
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    trigger: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default="new")
    # Value to Base: ERCOT load zone -> grid value per battery size -> recommended size.
    load_zone: Mapped[str | None] = mapped_column(String(20))
    battery_values: Mapped[dict | None] = mapped_column(JSONB)  # {"25": $/yr, "40": …, "50": …}
    recommended_kwh: Mapped[int | None] = mapped_column(Integer)
    sizing_reason: Mapped[str | None] = mapped_column(Text)
    value: Mapped[float | None] = mapped_column(Float)  # $/yr for the recommended size
    # score/100 × value: the default ranking ("priority").
    expected_value: Mapped[float | None] = mapped_column(Float, index=True)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SourceRun(Base):
    """One attempt to refresh one data source; powers the data-health page."""

    __tablename__ = "source_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String(60), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))  # running|success|skipped|failed
    fingerprint: Mapped[str | None] = mapped_column(Text)
    rows: Mapped[int | None] = mapped_column(Integer)
    inserted: Mapped[int | None] = mapped_column(Integer)
    updated: Mapped[int | None] = mapped_column(Integer)
    raw_path: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
