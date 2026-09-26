"""Load canonical frames into Postgres.

Each loader upserts via COPY into a temp table, stamps first/last-seen times with the
run's `now`, and returns (inserted, updated) counts. Change tracking lives here:
- properties.owner_changed_at is set when a known account gets a different owner;
- meters/permits.first_seen_at is set once, so later rows are "new since baseline".
"""

from datetime import datetime

import pandas as pd
from sqlalchemy import Connection, text

from app import geo
from app.db import engine
from app.leads.address import address_key, zip5
from app.leads.frames import METER_COLUMNS, PARCEL_COLUMNS, PERMIT_COLUMNS, PROPERTY_COLUMNS


def _copy(conn: Connection, table: str, like: str, df: pd.DataFrame) -> None:
    # Same column types as the target, no constraints.
    cols = ", ".join(df.columns)
    conn.execute(
        text(f"CREATE TEMP TABLE {table} ON COMMIT DROP AS SELECT {cols} FROM {like} WITH NO DATA")
    )
    cursor = conn.connection.cursor()
    with cursor.copy(f"COPY {table} ({', '.join(df.columns)}) FROM STDIN") as copy:
        for row in df.itertuples(index=False):
            copy.write_row([None if pd.isna(v) else v for v in row])


def _counts(conn: Connection, sql: str, now: datetime) -> tuple[int, int]:
    rows = conn.execute(text(sql), {"now": now}).scalars().all()
    inserted = sum(rows)
    return inserted, len(rows) - inserted


def _with_key(df: pd.DataFrame, street: str, zip_col: str) -> pd.DataFrame:
    df = df.copy()
    df[zip_col] = df[zip_col].map(zip5)
    df["address_key"] = [address_key(s, z) for s, z in zip(df[street], df[zip_col], strict=True)]
    return df


def load_properties(df: pd.DataFrame, now: datetime) -> tuple[int, int]:
    df = _with_key(df[PROPERTY_COLUMNS], "situs_address", "situs_zip")
    df = df.drop_duplicates(subset=["county", "account"], keep="last")
    cols = [*PROPERTY_COLUMNS, "address_key"]
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in ("county", "account"))
    with engine.begin() as conn:
        _copy(conn, "tmp_properties", "properties", df[cols])
        return _counts(
            conn,
            f"""
            INSERT INTO properties ({", ".join(cols)}, first_seen_at, last_seen_at)
            SELECT {", ".join(cols)}, :now, :now FROM tmp_properties
            ON CONFLICT (county, account) DO UPDATE SET {updates},
                last_seen_at = :now,
                owner_changed_at = CASE
                    WHEN properties.owner_name IS NOT NULL
                     AND EXCLUDED.owner_name IS NOT NULL
                     AND properties.owner_name <> EXCLUDED.owner_name THEN :now
                    ELSE properties.owner_changed_at END
            RETURNING (xmax = 0)
            """,
            now,
        )


def load_meters(df: pd.DataFrame, now: datetime) -> tuple[int, int]:
    df = _with_key(df[METER_COLUMNS], "address", "zip")
    df = df.sort_values("published_at").drop_duplicates(subset=["esiid"], keep="last")
    cols = [*METER_COLUMNS, "address_key"]
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "esiid")
    with engine.begin() as conn:
        _copy(conn, "tmp_meters", "meters", df[cols])
        return _counts(
            conn,
            f"""
            INSERT INTO meters ({", ".join(cols)}, first_seen_at, last_seen_at)
            SELECT {", ".join(cols)}, :now, :now FROM tmp_meters
            ON CONFLICT (esiid) DO UPDATE SET {updates}, last_seen_at = :now
            RETURNING (xmax = 0)
            """,
            now,
        )


def load_permits(df: pd.DataFrame, now: datetime) -> tuple[int, int]:
    df = _with_key(df[PERMIT_COLUMNS], "address", "zip")
    df = df.drop_duplicates(subset=["source", "permit_id"], keep="last")
    cols = [*PERMIT_COLUMNS, "address_key"]
    keys = ("source", "permit_id")
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in keys)
    with engine.begin() as conn:
        _copy(conn, "tmp_permits", "permits", df[cols])
        return _counts(
            conn,
            f"""
            INSERT INTO permits ({", ".join(cols)}, first_seen_at)
            SELECT {", ".join(cols)}, :now FROM tmp_permits
            ON CONFLICT (source, permit_id) DO UPDATE SET {updates}
            RETURNING (xmax = 0)
            """,
            now,
        )


def _h3(lat: pd.Series, lon: pd.Series) -> list[str | None]:
    return [
        geo.latlng_to_cell(a, b) if pd.notna(a) and pd.notna(b) else None
        for a, b in zip(lat, lon, strict=True)
    ]


def load_locations(df: pd.DataFrame, now: datetime) -> tuple[int, int]:
    """Set lat/lon and the H3 Cell on known properties. Parcels without an appraisal account
    are ignored."""
    df = df[PARCEL_COLUMNS].drop_duplicates(subset=["county", "account"], keep="last").copy()
    df["h3_index"] = _h3(df["lat"], df["lon"])
    with engine.begin() as conn:
        _copy(conn, "tmp_parcels", "properties", df)
        updated = conn.execute(
            text(
                """
                UPDATE properties p SET lat = t.lat, lon = t.lon, h3_index = t.h3_index
                FROM tmp_parcels t
                WHERE p.county = t.county AND p.account = t.account
                  AND (p.lat IS DISTINCT FROM t.lat OR p.lon IS DISTINCT FROM t.lon
                       OR p.h3_index IS DISTINCT FROM t.h3_index)
                """
            )
        ).rowcount
    return 0, updated


def assign_cells() -> int:
    """Fill h3_index for every located property that lacks it (one-off backfill; the parcel
    loader keeps it current afterwards). Idempotent; returns the number set."""
    with engine.begin() as conn:
        rows = pd.read_sql(
            text("SELECT id, lat, lon FROM properties WHERE h3_index IS NULL AND lat IS NOT NULL"),
            conn,
        )
        if rows.empty:
            return 0
        rows["h3_index"] = _h3(rows["lat"], rows["lon"])
        conn.execute(
            text("UPDATE properties SET h3_index = :h3_index WHERE id = :id"),
            rows[["id", "h3_index"]].to_dict("records"),
        )
        return len(rows)


LOADERS = {
    "property": load_properties,
    "meter": load_meters,
    "permit": load_permits,
    "location": load_locations,
}
