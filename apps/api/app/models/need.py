from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, Date, DateTime, Float, Integer, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Cell(Base):
    """One H3 hexagon (see app.geo). Need is computed per Cell; features live elsewhere."""

    __tablename__ = "cells"

    h3_index: Mapped[str] = mapped_column(String(15), primary_key=True)
    resolution: Mapped[int] = mapped_column(SmallInteger)
    center_lat: Mapped[float] = mapped_column(Float)
    center_lng: Mapped[float] = mapped_column(Float)
    # GIST-indexed (geoalchemy2 creates the index) for viewport and spatial joins.
    geometry: Mapped[str] = mapped_column(Geometry("POLYGON", srid=4326), nullable=False)
    # ERCOT load zone of the Cell's center (app.grid.zones.zone_for_points); None when the
    # center is outside every zone polygon. Recomputed by `python -m app.need enrich`.
    load_zone: Mapped[str | None] = mapped_column(String(20))
    # Census county GEOID of the Cell's center, from the Market county files; resolves the
    # county-level outage features. Recomputed with load_zone.
    county_fips: Mapped[str | None] = mapped_column(String(5))


class CountyOutageFeatures(Base):
    """Observed Outage Exposure inputs for one Texas county, from EAGLE-I (county-level:
    every Cell in the county shares them). Rebuilt by `python -m app.need outage compute`."""

    __tablename__ = "county_outage_features"

    county_fips: Mapped[str] = mapped_column(String(5), primary_key=True)
    county_name: Mapped[str | None] = mapped_column(String(60))
    modeled_customers: Mapped[int] = mapped_column(Integer)
    # History covers up to this date; windows end here, not today.
    data_through: Mapped[date] = mapped_column(Date)
    years_observed: Mapped[int] = mapped_column(SmallInteger)
    in_reference: Mapped[bool] = mapped_column(Boolean)
    hours_per_customer_365d: Mapped[float | None] = mapped_column(Float)
    outage_events_365d: Mapped[int | None] = mapped_column(Integer)
    major_outage_events_365d: Mapped[int | None] = mapped_column(Integer)
    peak_pct_out_365d: Mapped[float | None] = mapped_column(Float)
    hours_per_customer_5y: Mapped[float | None] = mapped_column(Float)
    outage_events_5y: Mapped[int | None] = mapped_column(Integer)
    major_outage_events_5y: Mapped[int | None] = mapped_column(Integer)
    peak_pct_out_5y: Mapped[float | None] = mapped_column(Float)
    last_observed_major_outage_on: Mapped[date | None] = mapped_column(Date)
    # Texas percentile of 5-year outage hours per customer (null outside the Reference
    # Population); it alone is Observed Outage Exposure. Event counts are context only.
    hours_per_customer_pctl: Mapped[float | None] = mapped_column(Float)
    observed_exposure: Mapped[float | None] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UtilityReliability(Base):
    """Utility Reliability Need inputs for one Texas utility, from EIA-861 (5-year means).
    Rebuilt by `python -m app.need outage compute`."""

    __tablename__ = "utility_reliability_features"

    utility_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=False
    )  # EIA id
    utility_name: Mapped[str] = mapped_column(String(120))
    ownership: Mapped[str | None] = mapped_column(String(40))
    customers: Mapped[float | None] = mapped_column(Float)
    data_through_year: Mapped[int] = mapped_column(SmallInteger)
    years_used: Mapped[int] = mapped_column(SmallInteger)
    saidi_wo_med_5y: Mapped[float | None] = mapped_column(Float)  # minutes, normal conditions
    saifi_wo_med_5y: Mapped[float | None] = mapped_column(Float)
    saidi_w_med_5y: Mapped[float | None] = mapped_column(Float)  # incl. major event days
    saifi_w_med_5y: Mapped[float | None] = mapped_column(Float)
    reliability_need: Mapped[float | None] = mapped_column(Float)  # Texas percentile
    # Raw yearly values behind the means: {"2024": {"saidi_wo_med": 150.2, "saidi_w_med": …}}.
    yearly: Mapped[dict] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StormFeatures(Base):
    """Storm Exposure inputs for one statewide H3 res-6 cell (~36 km², the Reference
    Population), from IEM SV/TO/EW warning polygons. A res-8 Cell reads its res-6 parent.
    Rebuilt by `python -m app.need weather compute`."""

    __tablename__ = "storm_features"

    h3_index: Mapped[str] = mapped_column(String(15), primary_key=True)  # res-6 cell
    resolution: Mapped[int] = mapped_column(SmallInteger)
    data_through: Mapped[date] = mapped_column(Date)
    warning_days_5y: Mapped[int] = mapped_column(Integer)
    warning_days_365d: Mapped[int] = mapped_column(Integer)
    severe_thunderstorm_warnings_5y: Mapped[int] = mapped_column(Integer)
    tornado_warnings_5y: Mapped[int] = mapped_column(Integer)
    extreme_wind_warnings_5y: Mapped[int] = mapped_column(Integer)
    # NWS office that issued most of the cell's warnings (issuance-practice notes).
    issuing_office: Mapped[str | None] = mapped_column(String(3))
    storm_exposure: Mapped[float | None] = mapped_column(Float)  # Texas res-6 percentile
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CountyTemperatureFeatures(Base):
    """Temperature Extremes Exposure inputs for one Texas county, from measured nClimGrid
    daily temperature (not NWS advisories). Rebuilt by `python -m app.need weather compute`."""

    __tablename__ = "county_temperature_features"

    county_fips: Mapped[str] = mapped_column(String(5), primary_key=True)
    county_name: Mapped[str | None] = mapped_column(String(60))
    data_through: Mapped[date] = mapped_column(Date)
    heat_days_100f_5y: Mapped[int] = mapped_column(Integer)  # scored
    heat_days_95f_5y: Mapped[int] = mapped_column(Integer)  # context
    cold_days_28f_5y: Mapped[int] = mapped_column(Integer)  # scored
    cold_days_32f_5y: Mapped[int] = mapped_column(Integer)  # context
    heat_days_100f_365d: Mapped[int] = mapped_column(Integer)
    heat_days_95f_365d: Mapped[int] = mapped_column(Integer)
    cold_days_28f_365d: Mapped[int] = mapped_column(Integer)
    cold_days_32f_365d: Mapped[int] = mapped_column(Integer)
    heat_100f_pctl: Mapped[float | None] = mapped_column(Float)
    cold_28f_pctl: Mapped[float | None] = mapped_column(Float)
    temperature_exposure: Mapped[float | None] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
