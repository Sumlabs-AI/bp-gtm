import pandas as pd
from sqlalchemy import text

from app.db import engine
from app.grid.sources import COLUMNS


def upsert_prices(df: pd.DataFrame) -> int:
    """Upsert a price frame into grid_prices via COPY into a temp table. Idempotent."""
    if df.empty:
        return 0
    df = df.drop_duplicates(subset=COLUMNS[:3], keep="last")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TEMP TABLE tmp_prices (LIKE grid_prices INCLUDING DEFAULTS) ON COMMIT DROP"
            )
        )
        cursor = conn.connection.cursor()
        with cursor.copy(f"COPY tmp_prices ({', '.join(COLUMNS)}) FROM STDIN") as copy:
            for row in df.itertuples(index=False):
                copy.write_row(row)
        conn.execute(
            text(
                """
                INSERT INTO grid_prices (settlement_point, market, interval_start, price)
                SELECT settlement_point, market, interval_start, price FROM tmp_prices
                ON CONFLICT (settlement_point, market, interval_start)
                DO UPDATE SET price = EXCLUDED.price
                """
            )
        )
    return len(df)


def load_prices(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """All tracked prices with start <= interval_start < end."""
    return pd.read_sql(
        text(
            "SELECT settlement_point, market, interval_start, price FROM grid_prices "
            "WHERE interval_start >= :start AND interval_start < :end"
        ),
        engine,
        params={"start": start.to_pydatetime(), "end": end.to_pydatetime()},
    )
