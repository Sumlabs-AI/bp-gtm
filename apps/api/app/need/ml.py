"""The ML contract (wiki/ml-contract.md): static Need features out, Propensity in, both
keyed by H3 res-8 `h3_index` and stamped with the Feature Version.

Out: need_features.parquet (1 row = 1 product Cell) and need_reference_res6.parquet (1 row
= 1 Texas res-6 reference cell; a different grain, for statewide training context).
No live columns: alerts, forecasts and ERCOT conditions are activation signals, not
training features.

In: propensity.parquet, validated strictly (res-8 H3, score 0-100, required columns).
History is kept; the API serves the latest prediction per Cell.
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
from app.models import CellPropensity, PropensityImport
from app.need.config import FEATURE_VERSION, UTILITY_BY_COUNTY, UTILITY_BY_LOAD_ZONE

FEATURES_FILE = "need_features.parquet"
REFERENCE_FILE = "need_reference_res6.parquet"

# Static features per product Cell. Utility comes from the same config the API uses.
FEATURES_SQL = """
SELECT
    c.h3_index, c.resolution, c.center_lat, c.center_lng,
    c.county_fips, c.load_zone,
    o.hours_per_customer_5y  AS outage_hours_per_customer_5y,
    o.outage_events_5y,
    o.major_outage_events_5y,
    o.peak_pct_out_5y        AS peak_customers_out_pct_5y,
    o.hours_per_customer_365d AS outage_hours_per_customer_365d,
    u.utility_id,
    u.saidi_wo_med_5y        AS utility_saidi_wo_med_5y,
    u.saifi_wo_med_5y        AS utility_saifi_wo_med_5y,
    s.warning_days_5y        AS storm_warning_days_5y,
    s.severe_thunderstorm_warnings_5y,
    s.tornado_warnings_5y,
    t.heat_days_100f_5y, t.heat_days_95f_5y, t.cold_days_28f_5y, t.cold_days_32f_5y,
    o.observed_exposure      AS observed_outage_exposure,
    u.reliability_need       AS utility_reliability_need,
    -- Outage Need Component: mean of the sub-scores that exist (app.need.components).
    ROUND(CAST((COALESCE(o.observed_exposure, 0) + COALESCE(u.reliability_need, 0)) /
          NULLIF((o.observed_exposure IS NOT NULL)::int + (u.reliability_need IS NOT NULL)::int, 0)
          AS numeric), 1)::float8 AS outage_need,
    s.storm_exposure,
    t.temperature_exposure   AS temperature_extremes_exposure,
    b.weather_input          AS weather_need,
    b.raw                    AS baseline_need_raw,
    b.baseline_need,
    b.dominant_driver,
    o.data_through           AS outage_data_through,
    u.data_through_year      AS utility_data_through_year,
    s.data_through           AS storm_data_through,
    t.data_through           AS temperature_data_through
FROM cells c
LEFT JOIN county_outage_features o ON o.county_fips = c.county_fips
LEFT JOIN utility_reliability u ON u.utility_id = :utility_id_expr
LEFT JOIN storm_features s ON s.h3_index = :res6_of_cell
LEFT JOIN county_temperature_features t ON t.county_fips = c.county_fips
LEFT JOIN cell_baseline_needs b ON b.h3_index = c.h3_index
ORDER BY c.h3_index
"""

REFERENCE_SQL = """
SELECT
    r.h3_index, 6 AS resolution, r.county_fips,
    s.warning_days_5y        AS storm_warning_days_5y,
    t.heat_days_100f_5y, t.cold_days_28f_5y,
    o.hours_per_customer_5y  AS outage_hours_per_customer_5y,
    o.major_outage_events_5y,
    r.outage_input           AS observed_outage_exposure,
    s.storm_exposure,
    t.temperature_exposure   AS temperature_extremes_exposure,
    r.weather_input          AS weather_need,
    r.raw                    AS baseline_need_raw
FROM baseline_need_references r
LEFT JOIN storm_features s ON s.h3_index = r.h3_index
LEFT JOIN county_outage_features o ON o.county_fips = r.county_fips
LEFT JOIN county_temperature_features t ON t.county_fips = r.county_fips
ORDER BY r.h3_index
"""

INT_COLUMNS = {
    "resolution",
    "outage_events_5y",
    "major_outage_events_5y",
    "utility_id",
    "storm_warning_days_5y",
    "severe_thunderstorm_warnings_5y",
    "tornado_warnings_5y",
    "heat_days_100f_5y",
    "heat_days_95f_5y",
    "cold_days_28f_5y",
    "cold_days_32f_5y",
    "utility_data_through_year",
}


@dataclass
class ExportReport:
    feature_version: str
    cells: int
    reference_cells: int
    features_path: Path
    reference_path: Path


def _utility_id_sql() -> str:
    """The Cell -> utility rule (config) as SQL, so the export and the API can't disagree."""
    zone = " ".join(f"WHEN c.load_zone = '{z}' THEN {u}" for z, u in UTILITY_BY_LOAD_ZONE.items())
    county = " ".join(f"WHEN c.county_fips = '{f}' THEN {u}" for f, u in UTILITY_BY_COUNTY.items())
    return f"(CASE {zone} {county} ELSE NULL END)"


def _typed(frame: pd.DataFrame, exported_at: datetime) -> pd.DataFrame:
    for column in INT_COLUMNS & set(frame.columns):
        frame[column] = frame[column].astype("Int32")
    frame["feature_version"] = FEATURE_VERSION
    frame["exported_at"] = exported_at
    return frame


def _write(frame: pd.DataFrame, path: Path) -> None:
    duckdb.from_df(frame).write_parquet(str(path), compression="zstd")


def export_features(out_dir: Path) -> ExportReport:
    """Write need_features.parquet and need_reference_res6.parquet into `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    exported_at = datetime.now(UTC)
    sql = FEATURES_SQL.replace(":utility_id_expr", _utility_id_sql()).replace(
        ":res6_of_cell", "h3_parent(c.h3_index)"
    )
    with engine.connect() as conn:
        cells = pd.read_sql(text("SELECT h3_index FROM cells"), conn)
        parents = {h: geo.cell_to_parent(h, 6) for h in cells["h3_index"]}
        conn.execute(
            text("CREATE TEMP TABLE cell_parents (h3_index VARCHAR(15), h3_res6 VARCHAR(15))")
        )
        if parents:
            conn.execute(
                text("INSERT INTO cell_parents VALUES (:h3_index, :h3_res6)"),
                [{"h3_index": h, "h3_res6": p} for h, p in parents.items()],
            )
        features = pd.read_sql(
            text(
                sql.replace("h3_parent(c.h3_index)", "cp.h3_res6")
                .replace(
                    "FROM cells c", "FROM cells c JOIN cell_parents cp ON cp.h3_index = c.h3_index"
                )
                .replace("c.county_fips, c.load_zone,", "cp.h3_res6, c.county_fips, c.load_zone,")
            ),
            conn,
        )
        reference = pd.read_sql(text(REFERENCE_SQL), conn)
    centers = reference["h3_index"].map(geo.cell_to_center)
    reference.insert(2, "center_lat", [c[0] for c in centers])
    reference.insert(3, "center_lng", [c[1] for c in centers])
    features_path, reference_path = out_dir / FEATURES_FILE, out_dir / REFERENCE_FILE
    _write(_typed(features, exported_at), features_path)
    _write(_typed(reference, exported_at), reference_path)
    return ExportReport(
        FEATURE_VERSION, len(features), len(reference), features_path, reference_path
    )


# ---- Propensity in ---------------------------------------------------------------------

REQUIRED = ["h3_index", "propensity_score", "model_version", "feature_version", "scored_at"]


class ImportError_(ValueError):
    """The file was rejected as a whole; nothing was stored."""


@dataclass
class ImportReport:
    rows: int
    product_cells: int
    other_cells: int
    model_versions: list[str]
    feature_versions: list[str]
    warnings: list[str] = field(default_factory=list)


def _validate(frame: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED if c not in frame.columns]
    if missing:
        raise ImportError_(f"missing required column(s): {', '.join(missing)}")
    if frame[REQUIRED].isna().any().any():
        bad = frame[frame[REQUIRED].isna().any(axis=1)].head(5)
        raise ImportError_(f"null in a required column, e.g. rows {list(bad.index)}")
    invalid = [
        i for i, h in frame["h3_index"].items() if not isinstance(h, str) or not geo.is_cell(h)
    ]
    if invalid:
        raise ImportError_(f"invalid h3_index at rows {invalid[:5]}")
    wrong_res = [i for i, h in frame["h3_index"].items() if geo.cell_resolution(h) != 8]
    if wrong_res:
        raise ImportError_(f"h3_index must be resolution 8, rows {wrong_res[:5]}")
    scores = pd.to_numeric(frame["propensity_score"], errors="coerce")
    out_of_range = frame.index[scores.isna() | (scores < 0) | (scores > 100)].tolist()
    if out_of_range:
        raise ImportError_(
            f"propensity_score must be a number in 0..100 (not a 0..1 probability), rows "
            f"{out_of_range[:5]}"
        )


def import_propensity(db: Session, path: Path) -> ImportReport:
    """Validate and store a propensity.parquet. Rejects the whole file on any invalid row.
    The caller commits."""
    frame = duckdb.read_parquet(str(path)).df()
    _validate(frame)
    scored_at = pd.to_datetime(frame["scored_at"], utc=True)
    now = datetime.now(UTC)
    product = set(db.scalars(select(text("h3_index")).select_from(text("cells"))))
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
            index_elements=["h3_index", "model_version", "scored_at"],
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


def latest_propensity(db: Session, cells: list[str]) -> dict[str, CellPropensity]:
    """h3_index -> the prediction with the latest scored_at (ties: latest import)."""
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
    return {p.h3_index: p for p in rows}
