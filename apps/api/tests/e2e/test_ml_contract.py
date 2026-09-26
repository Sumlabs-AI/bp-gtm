"""ML contract: need_features / need_reference_res6 out, propensity in, keyed by h3_index."""

from datetime import UTC, date, datetime, timedelta

import duckdb
import pandas as pd
import pytest

from app import geo
from app.db import SessionLocal
from app.models import CellPropensity
from app.need.baseline import compute_baseline
from app.need.config import FEATURE_VERSION
from app.need.enrich import enrich_counties, enrich_load_zones
from app.need.ml import ImportError_, export_features, import_propensity
from app.need.outage.store import save_county_features, save_utility_reliability
from app.need.store import seed_polygon
from app.need.weather.store import save_county_temperature, save_storm_features

HOUSTON = (29.7604, -95.3698)
AUSTIN = (30.2672, -97.7431)
H8, A8 = geo.latlng_to_cell(*HOUSTON), geo.latlng_to_cell(*AUSTIN)
H6, A6 = geo.cell_to_parent(H8, 6), geo.cell_to_parent(A8, 6)
COUNTY_OF = {H6: "48201", A6: "48453"}
LIVE_WORDS = ("alert", "forecast", "prc", "eea", "rt_price", "dam_price", "grid_state")


def square(lat: float, lng: float, d: float = 0.004) -> dict:
    ring = [[lng - d, lat - d], [lng + d, lat - d], [lng + d, lat + d], [lng - d, lat + d]]
    return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}


def county(fips: str, exposure: float) -> dict:
    return {
        "county_fips": fips,
        "county_name": fips,
        "modeled_customers": 1_000_000,
        "data_through": date(2025, 12, 31),
        "years_observed": 5,
        "in_reference": True,
        "hours_per_customer_365d": 2.0,
        "outage_events_365d": 12,
        "major_outage_events_365d": 1,
        "peak_pct_out_365d": 0.4,
        "hours_per_customer_5y": 118.5,
        "outage_events_5y": 70,
        "major_outage_events_5y": 9,
        "peak_pct_out_5y": 0.909,
        "last_observed_major_outage_on": date(2025, 10, 25),
        "hours_per_customer_pctl": exposure,
        "observed_exposure": exposure,
    }


def storm(h6: str, exposure: float) -> dict:
    return {
        "h3_index": h6,
        "resolution": 6,
        "data_through": date(2026, 9, 25),
        "issuing_office": "HGX",
        "warning_days_5y": 28,
        "warning_days_365d": 5,
        "severe_thunderstorm_warnings_5y": 60,
        "tornado_warnings_5y": 9,
        "extreme_wind_warnings_5y": 0,
        "storm_exposure": exposure,
    }


def temperature(fips: str, exposure: float) -> dict:
    return {
        "county_fips": fips,
        "county_name": fips,
        "data_through": date(2026, 2, 28),
        "heat_days_100f_5y": 37,
        "heat_days_95f_5y": 261,
        "cold_days_28f_5y": 26,
        "cold_days_32f_5y": 43,
        "heat_days_100f_365d": 3,
        "heat_days_95f_365d": 50,
        "cold_days_28f_365d": 4,
        "cold_days_32f_365d": 9,
        "heat_100f_pctl": exposure,
        "cold_28f_pctl": exposure,
        "temperature_exposure": exposure,
    }


@pytest.fixture
def world():
    with SessionLocal() as db:
        for p in (HOUSTON, AUSTIN):
            seed_polygon(db, square(*p))
        enrich_load_zones(db)
        enrich_counties(db)
        now = datetime.now(UTC)
        save_county_features(db, pd.DataFrame([county("48201", 75.7), county("48453", 51.6)]), now)
        save_utility_reliability(
            db,
            pd.DataFrame(
                [
                    {
                        "utility_id": 8901,
                        "utility_name": "CenterPoint Energy",
                        "ownership": "x",
                        "customers": 1.0,
                        "data_through_year": 2024,
                        "years_used": 5,
                        "saidi_wo_med_5y": 150.5,
                        "saifi_wo_med_5y": 1.2,
                        "saidi_w_med_5y": 1498.6,
                        "saifi_w_med_5y": 2.0,
                        "reliability_need": 46.3,
                        "yearly": {},
                    }
                ]
            ),
            now,
        )
        # Only Houston's res-6 has storm data: Austin's Cells must get nulls, not zeros.
        save_storm_features(db, pd.DataFrame([storm(H6, 57.6)]), now)
        save_county_temperature(db, pd.DataFrame([temperature("48201", 8.2)]), now)
        compute_baseline(db, county_of=lambda cells: {h: COUNTY_OF[h] for h in cells})
        db.commit()


def test_need_features_export_is_one_typed_row_per_cell(world, tmp_path):
    report = export_features(tmp_path)
    f = duckdb.read_parquet(str(tmp_path / "need_features.parquet")).df()
    assert report.cells == len(f) == 2
    assert f["h3_index"].is_unique
    houston = f.set_index("h3_index").loc[H8]
    assert (houston["resolution"], houston["h3_res6"]) == (8, H6)
    assert (houston["county_fips"], houston["load_zone"]) == ("48201", "LZ_HOUSTON")
    assert houston["outage_hours_per_customer_5y"] == 118.5
    assert houston["major_outage_events_5y"] == 9
    assert houston["peak_customers_out_pct_5y"] == pytest.approx(0.909)
    assert (houston["utility_id"], houston["utility_saidi_wo_med_5y"]) == (8901, 150.5)
    assert houston["storm_warning_days_5y"] == 28
    assert houston["heat_days_100f_5y"] == 37 and houston["cold_days_28f_5y"] == 26
    assert houston["observed_outage_exposure"] == 75.7
    assert houston["utility_reliability_need"] == 46.3
    assert houston["outage_need"] == 61.0
    assert houston["storm_exposure"] == 57.6
    assert houston["temperature_extremes_exposure"] == 8.2
    assert houston["weather_need"] == pytest.approx((57.6 + 8.2) / 2)
    assert houston["baseline_need_raw"] == pytest.approx(83.6, abs=0.1)
    assert houston["dominant_driver"] == "outage"
    assert pd.Timestamp(houston["outage_data_through"]) == pd.Timestamp("2025-12-31")
    assert houston["utility_data_through_year"] == 2024
    assert houston["feature_version"] == FEATURE_VERSION
    assert houston["exported_at"] is not None
    # No live columns: the model must not train on time-of-day signals.
    assert not [c for c in f.columns if any(w in c for w in LIVE_WORDS)]


def test_missing_features_are_null_not_zero(world, tmp_path):
    export_features(tmp_path)
    f = duckdb.read_parquet(str(tmp_path / "need_features.parquet")).df().set_index("h3_index")
    austin = f.loc[A8]
    assert pd.isna(austin["storm_warning_days_5y"]) and pd.isna(austin["storm_exposure"])
    assert pd.isna(austin["heat_days_100f_5y"]) and pd.isna(austin["weather_need"])
    assert pd.isna(austin["utility_id"]) and pd.isna(austin["utility_reliability_need"])
    assert austin["observed_outage_exposure"] == 51.6
    types = duckdb.sql(f"DESCRIBE SELECT * FROM '{tmp_path / 'need_features.parquet'}'").df()
    kinds = dict(zip(types["column_name"], types["column_type"], strict=True))
    assert kinds["storm_warning_days_5y"] == "INTEGER" and kinds["h3_index"] == "VARCHAR"
    assert kinds["outage_data_through"] == "DATE" and kinds["baseline_need"] == "DOUBLE"


def test_reference_export_is_the_statewide_res6_grain(world, tmp_path):
    report = export_features(tmp_path)
    r = duckdb.read_parquet(str(tmp_path / "need_reference_res6.parquet")).df()
    assert report.reference_cells == len(r) == 1  # every res-6 cell with storm data
    row = r.iloc[0]
    assert (row["h3_index"], row["resolution"], row["county_fips"]) == (H6, 6, "48201")
    assert row["storm_warning_days_5y"] == 28 and row["observed_outage_exposure"] == 75.7
    assert row["baseline_need_raw"] == pytest.approx(83.6, abs=0.1)
    assert row["feature_version"] == FEATURE_VERSION
    assert "baseline_need" not in r.columns  # the reference is ranked against, not ranked


def propensity_file(tmp_path, rows: list[dict], name: str = "propensity.parquet"):
    frame = pd.DataFrame(rows)
    path = tmp_path / name
    duckdb.from_df(frame).write_parquet(str(path))
    return path


def prediction(
    h3: str,
    score: float,
    version: str = "v1",
    scored_at: datetime | None = None,
    feature_version: str = FEATURE_VERSION,
) -> dict:
    return {
        "h3_index": h3,
        "propensity_score": score,
        "model_version": version,
        "feature_version": feature_version,
        "scored_at": scored_at or datetime(2026, 9, 26, 12, tzinfo=UTC),
    }


def latest(h3: str) -> CellPropensity | None:
    with SessionLocal() as db:
        from app.need.ml import latest_propensity

        return latest_propensity(db, [h3]).get(h3)


def test_valid_predictions_are_stored_and_reported(world, tmp_path):
    other = geo.latlng_to_cell(29.5, -95.5)  # a valid res-8 Cell we haven't seeded
    path = propensity_file(
        tmp_path, [prediction(H8, 92.0), prediction(A8, 40.5), prediction(other, 10.0)]
    )
    with SessionLocal() as db:
        report = import_propensity(db, path)
        db.commit()
    assert (report.rows, report.product_cells, report.other_cells) == (3, 2, 1)
    assert report.warnings == []
    assert latest(H8).propensity_score == 92.0
    assert latest(other).propensity_score == 10.0


@pytest.mark.parametrize(
    "bad, match",
    [
        ({"h3_index": "not-a-cell"}, "h3_index"),
        ({"h3_index": H6}, "resolution 8"),
        ({"propensity_score": 101.0}, r"0\.\.100"),
        ({"propensity_score": -0.1}, r"0\.\.100"),
    ],
)
def test_invalid_rows_reject_the_whole_file(world, tmp_path, bad, match):
    rows = [prediction(H8, 50.0), {**prediction(A8, 50.0), **bad}]
    path = propensity_file(tmp_path, rows)
    with SessionLocal() as db, pytest.raises(ImportError_, match=match):
        import_propensity(db, path)
    assert latest(H8) is None  # nothing stored


def test_missing_required_column_rejects_the_file(world, tmp_path):
    rows = [{k: v for k, v in prediction(H8, 50.0).items() if k != "model_version"}]
    with SessionLocal() as db, pytest.raises(ImportError_, match="model_version"):
        import_propensity(db, propensity_file(tmp_path, rows))


def test_history_is_kept_and_the_latest_prediction_is_served(world, tmp_path):
    t1 = datetime(2026, 9, 20, 12, tzinfo=UTC)
    t2 = t1 + timedelta(days=5)
    with SessionLocal() as db:
        import_propensity(
            db, propensity_file(tmp_path, [prediction(H8, 70.0, "v1", t1)], "a.parquet")
        )
        import_propensity(
            db, propensity_file(tmp_path, [prediction(H8, 70.0, "v1", t1)], "a2.parquet")
        )
        import_propensity(
            db, propensity_file(tmp_path, [prediction(H8, 85.0, "v2", t2)], "b.parquet")
        )
        import_propensity(
            db,
            propensity_file(
                tmp_path, [prediction(H8, 60.0, "v1", t1 - timedelta(days=1))], "c.parquet"
            ),
        )
        db.commit()
        history = db.query(CellPropensity).filter(CellPropensity.h3_index == H8).all()
    assert len(history) == 3  # the re-import upserted, the older prediction is kept
    served = latest(H8)
    assert (served.propensity_score, served.model_version) == (85.0, "v2")


def test_other_feature_version_is_accepted_with_a_warning(world, tmp_path):
    path = propensity_file(tmp_path, [prediction(H8, 50.0, feature_version="0.9.0")])
    with SessionLocal() as db:
        report = import_propensity(db, path)
        db.commit()
    assert any("0.9.0" in w and FEATURE_VERSION in w for w in report.warnings)


def test_api_shows_propensity_beside_baseline_without_combining(client, world, tmp_path):
    with SessionLocal() as db:
        import_propensity(db, propensity_file(tmp_path, [prediction(H8, 92.0, "v3")]))
        db.commit()
    cell = client.get(f"/need/cells/{H8}").json()
    assert cell["propensity"]["score"] == 92.0
    assert cell["propensity"]["modelVersion"] == "v3"
    assert cell["propensity"]["featureVersion"] == FEATURE_VERSION
    assert cell["baseline"]["baselineNeed"] is not None
    assert cell["needScore"] is None
    assert "opportunity" not in {k.lower() for k in cell}
    assert client.get(f"/need/cells/{A8}").json()["propensity"] is None
    body = client.get("/need/cells", params={"bbox": "-98.1,29.6,-95.2,30.5"}).json()
    props = {f["id"]: f["properties"] for f in body["features"]}
    assert (props[H8]["propensityScore"], props[A8]["propensityScore"]) == (92.0, None)
