"""End-to-end tests: real Postgres (migrated with Alembic) + the FastAPI app over HTTP.

Needs Postgres running (`docker compose up -d db`); the `app_test` database is created
and migrated automatically.
"""

from pathlib import Path

import geopandas as gpd
import psycopg
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from shapely.geometry import box
from sqlalchemy import text

from alembic import command
from app.db import engine
from app.main import app

API_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session", autouse=True)
def database():
    url = engine.url
    assert url.database and url.database.endswith("_test"), f"refusing to use {url.database}"
    admin = url.set(database="postgres", drivername="postgresql")
    try:
        with psycopg.connect(admin.render_as_string(hide_password=False), autocommit=True) as c:
            exists = c.execute("SELECT 1 FROM pg_database WHERE datname = %s", [url.database])
            if not exists.fetchone():
                c.execute(f'CREATE DATABASE "{url.database}"')
    except psycopg.OperationalError as exc:
        pytest.exit(f"e2e tests need Postgres (docker compose up -d db): {exc}", returncode=1)
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def clean_tables(database):
    with engine.begin() as conn:
        tables = conn.execute(
            text(
                "SELECT string_agg(quote_ident(tablename), ', ') FROM pg_tables "
                "WHERE schemaname = 'public' "
                # spatial_ref_sys is PostGIS's own SRID catalog, not app data.
                "AND tablename NOT IN ('alembic_version', 'spatial_ref_sys')"
            )
        ).scalar_one()
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def census_block_groups(monkeypatch):
    """Two fake block groups (west of downtown Houston 20% electric heat, east 60%) so
    scoring never downloads Census files."""
    groups = gpd.GeoDataFrame(
        {"geoid": ["1", "2"], "households": [100, 100], "electric_share": [0.2, 0.6]},
        geometry=[box(-96.0, 29.4, -95.3, 30.2), box(-95.3, 29.4, -94.9, 30.2)],
        crs=4326,
    )
    monkeypatch.setattr("app.leads.consumption.block_group_heating", lambda: groups)
    return groups


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
