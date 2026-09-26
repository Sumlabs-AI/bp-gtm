import os

# Point every test at a dedicated database BEFORE app modules are imported (app.db builds
# its engine from settings at import time). e2e tests truncate tables, so this must never
# be the dev database. Override with TEST_DATABASE_URL.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://app:app@localhost:5432/app_test"
)
