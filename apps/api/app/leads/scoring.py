"""Turn properties + meters + permits into scored, explained leads.

Eligibility (all required): single-family, homestead (owner-occupied), not confidential,
and the address matches an active residential meter on a TDSP Base serves.

Drivers are 0-100: home size and value are percentiles among eligible homes; the other
drivers are yes/no signals (100 or 0). Score = weighted average (weights in config.py).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import and_, case, or_, text
from sqlalchemy.dialects.postgresql import insert

from app.db import engine
from app.leads.config import BASE_TDSPS, LeadScoringConfig
from app.leads.value import assign_zones, recommend_battery, zone_battery_values
from app.models import Lead


@dataclass(frozen=True)
class Driver:
    key: str
    label: str
    reason: str  # phrase for the one-line reason


DRIVERS = [
    Driver("home_size", "Home size", "large home"),
    Driver("solar", "Solar installed", "has solar"),
    Driver("home_value", "Home value", "high home value"),
    Driver("ev_charger", "EV charger", "has an EV charger"),
    Driver("new_owner", "New owner", "recently changed hands"),
    Driver("new_home", "New home", "newly built"),
    Driver("pool", "Pool or spa", "has a pool (big electric load)"),
]
DRIVERS_BY_KEY = {d.key: d for d in DRIVERS}
PERMIT_SIGNALS = {"solar": "solar", "ev_charger": "ev_charger", "new_home": "new_home"}
TRIGGER_LABELS = {
    "solar": "New solar permit",
    "ev_charger": "New EV charger permit",
    "new_home": "New home permit",
    "new_meter": "New electric meter",
    "new_owner": "New owner",
    "newly_eligible": "Newly eligible",
}


def reasons(scores: dict[str, float], weights: dict[str, float]) -> str:
    ranked = sorted(weights, key=lambda k: weights[k] * scores[k], reverse=True)
    strong = [DRIVERS_BY_KEY[k].reason for k in ranked[:2] if scores[k] >= 50]
    return (" and ".join(strong) + ".").capitalize() if strong else "No standout signal."


def _read(sql: str, **params) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)


def score_leads(now: datetime, cfg: LeadScoringConfig, baseline: bool = False) -> dict:
    """Rebuild leads. baseline=True (first run, or after changing matching/eligibility
    rules) records newly eligible homes without announcing them as news."""
    since = now - timedelta(days=cfg.signal_lookback_days)

    homes = _read(
        """
        SELECT id AS property_id, address_key, market_value, heated_sqft, year_built,
               owner_changed_at, has_solar, has_pool, lat, lon
        FROM properties
        WHERE is_single_family AND homestead AND NOT confidential AND address_key IS NOT NULL
        """
    )
    meters = _read(
        """
        SELECT DISTINCT ON (address_key) address_key, esiid, tdsp, first_seen_at,
               first_seen_at > (SELECT min(first_seen_at) FROM meters) AS is_new
        FROM meters
        WHERE tdsp = ANY(:tdsps) AND premise_type = 'residential' AND status = 'active'
          AND address_key IS NOT NULL
        ORDER BY address_key, first_seen_at
        """,
        tdsps=list(BASE_TDSPS),
    )
    permits = _read(
        """
        SELECT p.address_key, p.category, p.permit_id, p.source, p.issued_date, p.first_seen_at,
               p.first_seen_at > b.baseline AS is_new
        FROM permits p
        JOIN (SELECT source, min(first_seen_at) AS baseline FROM permits GROUP BY source) b
          USING (source)
        WHERE p.category = ANY(:cats) AND p.address_key IS NOT NULL AND p.issued_date >= :since
        """,
        cats=list(PERMIT_SIGNALS),
        since=since.date(),
    )
    existing = _read("SELECT property_id, first_seen_at, status FROM leads")

    eligible = homes.merge(meters, on="address_key", how="inner")
    summary = {"candidates": len(homes), "eligible": len(eligible)}
    if eligible.empty:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM leads"))
        return summary | {"new": 0}

    # Percentile drivers.
    drivers = pd.DataFrame(index=eligible.index)
    drivers["home_size"] = eligible["heated_sqft"].rank(pct=True).fillna(0) * 100
    drivers["home_value"] = eligible["market_value"].rank(pct=True).fillna(0) * 100

    by_key = permits.groupby("address_key")
    has = {cat: set(permits.loc[permits.category == cat, "address_key"]) for cat in PERMIT_SIGNALS}
    recent_build = eligible["year_built"].fillna(0) >= now.year - cfg.new_home_years
    drivers["solar"] = (eligible["address_key"].isin(has["solar"]) | eligible["has_solar"]) * 100.0
    drivers["pool"] = eligible["has_pool"] * 100.0
    drivers["ev_charger"] = eligible["address_key"].isin(has["ev_charger"]) * 100.0
    drivers["new_home"] = (
        recent_build | eligible["address_key"].isin(has["new_home"]) | eligible["is_new"]
    ) * 100.0
    owner_changed = pd.to_datetime(eligible["owner_changed_at"], utc=True)
    drivers["new_owner"] = (owner_changed >= since).fillna(False) * 100.0

    total = sum(cfg.weights.values())
    eligible["score"] = sum(drivers[k] * w for k, w in cfg.weights.items()) / total
    eligible["load_zone"] = assign_zones(eligible)
    battery_values = zone_battery_values()

    had_leads = not existing.empty and not baseline
    prior = existing.set_index("property_id")
    rows = []
    for i, home in eligible.iterrows():
        signals, events = [], []
        if home.address_key in by_key.groups:
            for p in by_key.get_group(home.address_key).itertuples():
                signals.append(
                    {
                        "type": p.category,
                        "date": str(p.issued_date),
                        "source": p.source,
                        "detail": f"Permit {p.permit_id}",
                    }
                )
                if p.is_new:
                    events.append((p.first_seen_at, p.category))
        if home.is_new:
            signals.append(
                {
                    "type": "new_meter",
                    "date": str(home.first_seen_at.date()),
                    "source": "ercot_tdsp_esiid_extract",
                    "detail": f"ESI ID {home.esiid}",
                }
            )
            events.append((home.first_seen_at, "new_meter"))
        if drivers.at[i, "new_owner"]:
            signals.append(
                {
                    "type": "new_owner",
                    "date": str(owner_changed[i].date()),
                    "source": "appraisal",
                    "detail": "Owner changed on the appraisal roll",
                }
            )
            events.append((owner_changed[i], "new_owner"))
        if home.has_solar:
            signals.append(
                {
                    "type": "solar",
                    "date": None,
                    "source": "appraisal",
                    "detail": "Solar PV panels on the appraisal record",
                }
            )
        if home.has_pool:
            signals.append(
                {
                    "type": "pool",
                    "date": None,
                    "source": "appraisal",
                    "detail": "Pool or spa on the appraisal record",
                }
            )
        if recent_build[i]:
            signals.append(
                {
                    "type": "new_home",
                    "date": None,
                    "source": "appraisal",
                    "detail": f"Built {int(home.year_built)}",
                }
            )
        is_new_lead = home.property_id not in prior.index
        first_seen = now if is_new_lead else prior.at[home.property_id, "first_seen_at"]
        if had_leads and is_new_lead:
            events.append((now, "newly_eligible"))
        when, trigger = max(events, key=lambda e: e[0]) if events else (None, None)

        scores = {k: round(float(drivers.at[i, k]), 1) for k in cfg.weights}
        score = round(float(home.score), 1)
        kwh, sizing_reason = recommend_battery(home.heated_sqft, bool(home.has_pool), cfg)
        zone = home.load_zone if isinstance(home.load_zone, str) else None
        values = battery_values.get(zone)
        value = values[str(kwh)] if values else None
        rows.append(
            {
                "property_id": int(home.property_id),
                "score": score,
                "load_zone": zone,
                "battery_values": values,
                "recommended_kwh": kwh,
                "sizing_reason": sizing_reason,
                "value": value,
                "expected_value": None if value is None else round(score / 100 * value, 0),
                "drivers": {
                    k: {"score": scores[k], "value": _driver_value(k, home, scores)}
                    for k in cfg.weights
                },
                "signals": signals,
                "reasons": reasons(scores, cfg.weights),
                "first_seen_at": first_seen,
                "triggered_at": when,
                "trigger": TRIGGER_LABELS.get(trigger),
                "scored_at": now,
            }
        )

    _write_leads(rows)
    window = now - timedelta(days=cfg.new_window_days)
    new = sum(1 for r in rows if r["triggered_at"] is not None and r["triggered_at"] >= window)
    return summary | {"new": new}


def _driver_value(key: str, home, scores: dict[str, float]):
    if key == "home_size":
        return None if pd.isna(home.heated_sqft) else float(home.heated_sqft)
    if key == "home_value":
        return None if pd.isna(home.market_value) else float(home.market_value)
    return scores[key] > 0


def _write_leads(rows: list[dict]) -> None:
    with engine.begin() as conn:
        ids = [r["property_id"] for r in rows]
        conn.execute(text("DELETE FROM leads WHERE NOT (property_id = ANY(:ids))"), {"ids": ids})
        # Postgres allows at most 65,535 bind parameters per statement.
        batch = 60_000 // len(rows[0])
        for chunk in range(0, len(rows), batch):
            stmt = insert(Lead).values(rows[chunk : chunk + batch])
            # Keep a trigger until a newer one replaces it ("newly eligible" only fires once).
            newer = or_(
                Lead.triggered_at.is_(None),
                and_(
                    stmt.excluded.triggered_at.is_not(None),
                    stmt.excluded.triggered_at >= Lead.triggered_at,
                ),
            )
            conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=["property_id"],
                    # first_seen_at and the reviewer's status survive re-scores.
                    set_={
                        **{
                            c: stmt.excluded[c]
                            for c in (
                                "score",
                                "drivers",
                                "signals",
                                "reasons",
                                "scored_at",
                                "load_zone",
                                "battery_values",
                                "recommended_kwh",
                                "sizing_reason",
                                "value",
                                "expected_value",
                            )
                        },
                        "triggered_at": case(
                            (newer, stmt.excluded.triggered_at), else_=Lead.triggered_at
                        ),
                        "trigger": case((newer, stmt.excluded.trigger), else_=Lead.trigger),
                    },
                )
            )
