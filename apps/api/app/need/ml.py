"""The ML contract (wiki/ml-contract.md): static Need features out, Propensity in, both
keyed by H3 res-8 `h3_index` and stamped with the Feature Version.

Out: need_features.parquet (1 row = 1 product Cell) and need_reference_res6.parquet (1 row
= 1 Texas res-6 reference cell; a different grain, for statewide training context).
No live columns: alerts, forecasts and ERCOT conditions are activation signals, not
training features.

In: propensity.parquet, validated strictly (res-8 H3, score 0-100, required columns,
timezone-aware scored_at). Any bad row rejects the whole file. History is kept; the API
serves the latest prediction per Cell.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import geo
from app.db import engine
from app.models import Cell, CellPropensity, PropensityImport
from app.need.components import mean_of_present
from app.need.config import FEATURE_VERSION
from app.need.outage.component import utility_for

FEATURES_FILE = "need_features.parquet"
REFERENCE_FILE = "need_reference_res6.parquet"

# The contract, column by column, with the Parquet type DuckDB reports. Order matters.
FEATURE_COLUMNS: dict[str, str] = {
    "h3_index": "VARCHAR",
    "resolution": "INTEGER",
    "center_lat": "DOUBLE",
    "center_lng": "DOUBLE",
    "h3_res6": "VARCHAR",
    "county_fips": "VARCHAR",
    "load_zone": "VARCHAR",
    "outage_hours_per_customer_5y": "DOUBLE",
    "outage_events_5y": "INTEGER",
    "major_outage_events_5y": "INTEGER",
    "peak_customers_out_pct_5y": "DOUBLE",
    "outage_hours_per_customer_365d": "DOUBLE",
    "utility_id": "INTEGER",
    "utility_saidi_wo_med_5y": "DOUBLE",
    "utility_saifi_wo_med_5y": "DOUBLE",
    "storm_warning_days_5y": "INTEGER",
    "severe_thunderstorm_warnings_5y": "INTEGER",
    "tornado_warnings_5y": "INTEGER",
    "heat_days_100f_5y": "INTEGER",
    "heat_days_95f_5y": "INTEGER",
    "cold_days_28f_5y": "INTEGER",
    "cold_days_32f_5y": "INTEGER",
    "observed_outage_exposure": "DOUBLE",
    "utility_reliability_need": "DOUBLE",
    "outage_need": "DOUBLE",
    "storm_exposure": "DOUBLE",
    "temperature_extremes_exposure": "DOUBLE",
    "weather_need": "DOUBLE",
    "baseline_need_raw": "DOUBLE",
    "baseline_need": "DOUBLE",
    "dominant_driver": "VARCHAR",
    "outage_data_through": "DATE",
    "utility_data_through_year": "INTEGER",
    "storm_data_through": "DATE",
    "temperature_data_through": "DATE",
    "feature_version": "VARCHAR",
    "exported_at": "TIMESTAMP WITH TIME ZONE",
}
REFERENCE_COLUMNS: dict[str, str] = {
    "h3_index": "VARCHAR",
    "resolution": "INTEGER",
    "center_lat": "DOUBLE",
    "center_lng": "DOUBLE",
    "county_fips": "VARCHAR",
    "storm_warning_days_5y": "INTEGER",
    "heat_days_100f_5y": "INTEGER",
    "cold_days_28f_5y": "INTEGER",
    "outage_hours_per_customer_5y": "DOUBLE",
    "major_outage_events_5y": "INTEGER",
    "observed_outage_exposure": "DOUBLE",
    "storm_exposure": "DOUBLE",
    "temperature_extremes_exposure": "DOUBLE",
    "weather_need": "DOUBLE",
    "baseline_need_raw": "DOUBLE",
    "feature_version": "VARCHAR",
    "exported_at": "TIMESTAMP WITH TIME ZONE",
}

# Product Cells joined to their features. `cell_parents` / `cell_utilities` are temp tables
# filled from the same Python rules the API uses (geo.cell_to_parent, utility_for).
FEATURES_SQL = """
SELECT
    c.h3_index, c.resolution, c.center_lat, c.center_lng, cp.h3_res6,
    c.county_fips, c.load_zone,
    o.hours_per_customer_5y   AS outage_hours_per_customer_5y,
    o.outage_events_5y, o.major_outage_events_5y,
    o.peak_pct_out_5y         AS peak_customers_out_pct_5y,
    o.hours_per_customer_365d AS outage_hours_per_customer_365d,
    u.utility_id,
    u.saidi_wo_med_5y         AS utility_saidi_wo_med_5y,
    u.saifi_wo_med_5y         AS utility_saifi_wo_med_5y,
    s.warning_days_5y         AS storm_warning_days_5y,
    s.severe_thunderstorm_warnings_5y, s.tornado_warnings_5y,
    t.heat_days_100f_5y, t.heat_days_95f_5y, t.cold_days_28f_5y, t.cold_days_32f_5y,
    o.observed_exposure       AS observed_outage_exposure,
    u.reliability_need        AS utility_reliability_need,
    s.storm_exposure,
    t.temperature_exposure    AS temperature_extremes_exposure,
    b.weather_input           AS weather_need,
    b.raw                     AS baseline_need_raw,
    b.baseline_need, b.dominant_driver,
    o.data_through            AS outage_data_through,
    u.data_through_year       AS utility_data_through_year,
    s.data_through            AS storm_data_through,
    t.data_through            AS temperature_data_through
FROM cells c
JOIN cell_parents cp ON cp.h3_index = c.h3_index
LEFT JOIN cell_utilities cu ON cu.h3_index = c.h3_index
LEFT JOIN county_outage_features o ON o.county_fips = c.county_fips
LEFT JOIN utility_reliability u ON u.utility_id = cu.utility_id
LEFT JOIN storm_features s ON s.h3_index = cp.h3_res6
LEFT JOIN county_temperature_features t ON t.county_fips = c.county_fips
LEFT JOIN cell_baseline_needs b ON b.h3_index = c.h3_index
ORDER BY c.h3_index
"""

REFERENCE_SQL = """
SELECT
    r.h3_index, 6 AS resolution, r.county_fips,
    s.warning_days_5y         AS storm_warning_days_5y,
    t.heat_days_100f_5y, t.cold_days_28f_5y,
    o.hours_per_customer_5y   AS outage_hours_per_customer_5y,
    o.major_outage_events_5y,
    r.outage_input            AS observed_outage_exposure,
    s.storm_exposure,
    t.temperature_exposure    AS temperature_extremes_exposure,
    r.weather_input           AS weather_need,
    r.raw                     AS baseline_need_raw
FROM baseline_need_references r
LEFT JOIN storm_features s ON s.h3_index = r.h3_index
LEFT JOIN county_outage_features o ON o.county_fips = r.county_fips
LEFT JOIN county_temperature_features t ON t.county_fips = r.county_fips
ORDER BY r.h3_index
"""


@dataclass
class ExportReport:
    feature_version: str
    cells: int
    reference_cells: int
    features_path: Path
    reference_path: Path
    feature_columns: list[str]
    reference_columns: list[str]


def _write(frame: pd.DataFrame, columns: dict[str, str], path: Path) -> None:
    """Parquet with the contract's exact column order and types (an all-null column would
    otherwise be written as INTEGER)."""
    frame = frame[list(columns)]
    con = duckdb.connect()
    con.register("frame", frame)
    casts = ", ".join(f'CAST("{c}" AS {t}) AS "{c}"' for c, t in columns.items())
    con.execute(f"COPY (SELECT {casts} FROM frame) TO '{path}' (FORMAT parquet, COMPRESSION zstd)")


def export_features(out_dir: Path) -> ExportReport:
    """Write need_features.parquet and need_reference_res6.parquet into `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    exported_at = datetime.now(UTC)
    with engine.begin() as conn:
        session = Session(bind=conn)
        cells = session.scalars(select(Cell)).all()
        conn.execute(
            text(
                "CREATE TEMP TABLE cell_parents (h3_index VARCHAR(15), h3_res6 VARCHAR(15)) "
                "ON COMMIT DROP"
            )
        )
        conn.execute(
            text(
                "CREATE TEMP TABLE cell_utilities (h3_index VARCHAR(15), utility_id INTEGER) "
                "ON COMMIT DROP"
            )
        )
        if cells:
            conn.execute(
                text("INSERT INTO cell_parents VALUES (:h3_index, :h3_res6)"),
                [
                    {"h3_index": c.h3_index, "h3_res6": geo.cell_to_parent(c.h3_index, 6)}
                    for c in cells
                ],
            )
            conn.execute(
                text("INSERT INTO cell_utilities VALUES (:h3_index, :utility_id)"),
                [{"h3_index": c.h3_index, "utility_id": utility_for(c)} for c in cells],
            )
        features = pd.read_sql(text(FEATURES_SQL), conn)
        reference = pd.read_sql(text(REFERENCE_SQL), conn)
    # Outage Need Component, from the same function the API uses.
    features["outage_need"] = [
        mean_of_present(o, u)
        for o, u in zip(
            features["observed_outage_exposure"]
            .astype(object)
            .where(features["observed_outage_exposure"].notna(), None),
            features["utility_reliability_need"]
            .astype(object)
            .where(features["utility_reliability_need"].notna(), None),
            strict=True,
        )
    ]
    centers = reference["h3_index"].map(geo.cell_to_center)
    reference["center_lat"] = [c[0] for c in centers]
    reference["center_lng"] = [c[1] for c in centers]
    for frame in (features, reference):
        frame["feature_version"] = FEATURE_VERSION
        frame["exported_at"] = exported_at
    features_path, reference_path = out_dir / FEATURES_FILE, out_dir / REFERENCE_FILE
    _write(features, FEATURE_COLUMNS, features_path)
    _write(reference, REFERENCE_COLUMNS, reference_path)
    return ExportReport(
        FEATURE_VERSION,
        len(features),
        len(reference),
        features_path,
        reference_path,
        list(FEATURE_COLUMNS),
        list(REFERENCE_COLUMNS),
    )


# ---- Propensity in ---------------------------------------------------------------------

REQUIRED = ["h3_index", "propensity_score", "model_version", "feature_version", "scored_at"]
KEY = ["h3_index", "model_version", "scored_at"]


class PropensityFileRejected(ValueError):
    """The file was rejected as a whole; nothing was stored."""


@dataclass
class ImportReport:
    rows: int
    product_cells: int
    other_cells: int
    model_versions: list[str]
    feature_versions: list[str]
    warnings: list[str] = field(default_factory=list)


def _read(path: Path) -> pd.DataFrame:
    try:
        return duckdb.read_parquet(str(path)).df()
    except Exception as exc:
        raise PropensityFileRejected(f"could not read {path.name} as Parquet: {exc}") from None


def _validate(frame: pd.DataFrame) -> pd.Series:
    """Raise on the first problem; return scored_at as timezone-aware UTC."""
    missing = [c for c in REQUIRED if c not in frame.columns]
    if missing:
        raise PropensityFileRejected(f"missing required column(s): {', '.join(missing)}")
    if frame.empty:
        raise PropensityFileRejected("the file is empty")
    if frame[REQUIRED].isna().any().any():
        bad = frame.index[frame[REQUIRED].isna().any(axis=1)].tolist()
        raise PropensityFileRejected(f"null in a required column at rows {bad[:5]}")
    invalid = [
        i for i, h in frame["h3_index"].items() if not isinstance(h, str) or not geo.is_cell(h)
    ]
    if invalid:
        raise PropensityFileRejected(f"invalid h3_index at rows {invalid[:5]}")
    wrong_res = [i for i, h in frame["h3_index"].items() if geo.cell_resolution(h) != 8]
    if wrong_res:
        raise PropensityFileRejected(f"h3_index must be resolution 8, rows {wrong_res[:5]}")
    scores = pd.to_numeric(frame["propensity_score"], errors="coerce")
    out_of_range = frame.index[scores.isna() | (scores < 0) | (scores > 100)].tolist()
    if out_of_range:
        raise PropensityFileRejected(
            "propensity_score must be a number in 0..100 (not a 0..1 probability), rows "
            f"{out_of_range[:5]}"
        )
    try:
        scored_at = pd.to_datetime(frame["scored_at"], utc=False)
    except (ValueError, TypeError) as exc:
        raise PropensityFileRejected(f"scored_at is not a timestamp: {exc}") from None
    if scored_at.dt.tz is None:
        raise PropensityFileRejected(
            "scored_at must be timezone-aware (e.g. UTC); naive timestamps are ambiguous"
        )
    duplicates = frame.index[frame.duplicated(KEY, keep=False)].tolist()
    if duplicates:
        raise PropensityFileRejected(
            f"duplicate (h3_index, model_version, scored_at) at rows {duplicates[:5]}"
        )
    return scored_at.dt.tz_convert("UTC")


def import_propensity(db: Session, path: Path) -> ImportReport:
    """Validate and store a propensity.parquet. Rejects the whole file on any invalid row.
    The caller commits."""
    frame = _read(path)
    scored_at = _validate(frame)
    now = datetime.now(UTC)
    product = set(db.scalars(select(Cell.h3_index)))
    in_product = frame["h3_index"].isin(product)
    feature_versions = sorted(frame["feature_version"].astype(str).unique())
    warnings = [
        f"feature_version {v} differs from the current Need Feature Version {FEATURE_VERSION}"
        for v in feature_versions
        if v != FEATURE_VERSION
    ]
    record = PropensityImport(
        imported_at=now,
        file_name=path.name,
        rows=len(frame),
        product_cells=int(in_product.sum()),
        other_cells=int((~in_product).sum()),
        model_versions=sorted(frame["model_version"].astype(str).unique()),
        feature_versions=feature_versions,
        warnings=warnings,
    )
    db.add(record)
    db.flush()
    rows = [
        {
            "h3_index": h,
            "propensity_score": float(score),
            "model_version": str(model),
            "feature_version": str(fv),
            "scored_at": at.to_pydatetime(),
            "imported_at": now,
            "import_id": record.id,
        }
        for h, score, model, fv, at in zip(
            frame["h3_index"],
            frame["propensity_score"],
            frame["model_version"],
            frame["feature_version"],
            scored_at,
            strict=True,
        )
    ]
    stmt = insert(CellPropensity).values(rows)
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=KEY,
            set_={
                "propensity_score": stmt.excluded.propensity_score,
                "feature_version": stmt.excluded.feature_version,
                "imported_at": stmt.excluded.imported_at,
                "import_id": stmt.excluded.import_id,
            },
        )
    )
    return ImportReport(
        rows=len(frame),
        product_cells=record.product_cells,
        other_cells=record.other_cells,
        model_versions=record.model_versions,
        feature_versions=feature_versions,
        warnings=warnings,
    )


def latest_propensity(db: Session, cells: list[str]) -> dict[str, CellPropensity | None]:
    """h3_index -> the prediction with the latest scored_at (ties: latest import), or None."""
    ranked = (
        select(
            CellPropensity.id,
            func.row_number()
            .over(
                partition_by=CellPropensity.h3_index,
                order_by=(CellPropensity.scored_at.desc(), CellPropensity.imported_at.desc()),
            )
            .label("rank"),
        )
        .where(CellPropensity.h3_index.in_(cells))
        .subquery()
    )
    rows = db.scalars(
        select(CellPropensity)
        .join(ranked, ranked.c.id == CellPropensity.id)
        .where(ranked.c.rank == 1)
    )
    found = {p.h3_index: p for p in rows}
    return {h: found.get(h) for h in cells}
