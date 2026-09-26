from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
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

    __tablename__ = "utility_reliability"

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


class NwsAlert(Base):
    """One official NWS Alert (not a derived Forecast Signal). NWS event time (effective/ends)
    is kept apart from our ingestion state (first/last seen, superseded). Rows are never deleted.
    Active-ness is decided at read time (app/need/live/store.py)."""

    __tablename__ = "nws_alerts"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)  # NWS alert id
    event: Mapped[str] = mapped_column(String(60))
    category: Mapped[str] = mapped_column(String(20))
    severity: Mapped[str | None] = mapped_column(String(20))
    certainty: Mapped[str | None] = mapped_column(String(20))
    urgency: Mapped[str | None] = mapped_column(String(20))
    message_type: Mapped[str | None] = mapped_column(String(20))
    headline: Mapped[str | None] = mapped_column(Text)
    sender: Mapped[str | None] = mapped_column(String(120))
    zones: Mapped[list[str]] = mapped_column(JSONB)  # UGC codes (empty for polygon alerts)
    # NWS event time.
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    onset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @hybrid_property
    def ends(self) -> datetime:
        """When the event ends: NWS `ends`, or `expires` when NWS gives no end."""
        return self.ends_at or self.expires_at

    @ends.inplace.expression
    @classmethod
    def _ends_expression(cls):
        return func.coalesce(cls.ends_at, cls.expires_at)

    # Area: the alert's own polygon, or the union of its NWS zones.
    geometry: Mapped[str] = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)
    geometry_source: Mapped[str] = mapped_column(String(10))  # "alert" | "zones"
    # Ingestion state.
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NwsAlertSnapshot(Base):
    """One attempt to fetch all active NWS alerts for Texas. Only a successful Snapshot may
    supersede signals; failed ones are logged and change nothing."""

    __tablename__ = "nws_alert_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    succeeded: Mapped[bool] = mapped_column(Boolean)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alerts_total: Mapped[int | None] = mapped_column(Integer)
    signals_kept: Mapped[int | None] = mapped_column(Integer)
    superseded: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)


class ForecastPoint(Base):
    """One forecast sample point: an H3 res-6 cell covering the Markets, with its NWS grid
    cell. Tracks its own freshness: each point is replaced only when its own fetch works."""

    __tablename__ = "forecast_points"

    h3_index: Mapped[str] = mapped_column(String(15), primary_key=True)  # res-6 cell
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    office: Mapped[str] = mapped_column(String(3))  # NWS grid office, e.g. HGX
    grid_x: Mapped[int] = mapped_column(Integer)
    grid_y: Mapped[int] = mapped_column(Integer)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # NWS `updateTime` of the forecast last fetched successfully (not our fetch time).
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class ForecastRun(Base):
    """One hourly forecast refresh attempt over every point, plus the SPC outlooks."""

    __tablename__ = "forecast_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    points_ok: Mapped[int] = mapped_column(Integer, server_default="0")
    points_failed: Mapped[int] = mapped_column(Integer, server_default="0")
    spc_ok: Mapped[bool] = mapped_column(Boolean, server_default="false")
    spc_error: Mapped[str | None] = mapped_column(Text)


class ForecastSignal(Base):
    """A Forecast Signal: our reading of NWS grid / SPC outlook data (never an NWS Alert).
    Rows are never deleted; a newer successful fetch for the point sets `replaced_at`."""

    __tablename__ = "forecast_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("forecast_runs.id"), index=True)
    h3_index: Mapped[str] = mapped_column(String(15), index=True)  # res-6 forecast point
    source: Mapped[str] = mapped_column(String(20))  # "nws_grid" | "spc_outlook"
    condition: Mapped[str] = mapped_column(String(20))  # wind|heat|cold|ice|severe_storm
    level: Mapped[str] = mapped_column(String(10))  # "elevated" | "high"
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    peak_value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(10))
    threshold: Mapped[float | None] = mapped_column(Float)  # the threshold that produced it
    label: Mapped[str | None] = mapped_column(String(10))  # SPC category, e.g. ENH
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # NWS/SPC
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # ours
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
