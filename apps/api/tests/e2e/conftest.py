"""End-to-end tests: real Postgres (migrated with Alembic) + the FastAPI app over HTTP.

Needs Postgres running (`docker compose up -d db`); the `app_test` database is created
and migrated automatically.
"""

from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
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
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        ).scalar_one()
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
