# Grid economics

The grid economics feature ranks ERCOT load zones by where Base may want more
batteries. It is a zone-level historical screen, not a site recommendation or a
forecast of battery profit.

## Code and data flow

- `apps/api/app/grid/` contains the sources, zone list, metrics, scoring,
  database helpers, assumptions, and CLI.
- `apps/api/app/routers/grid.py` serves the latest computed results.
- `apps/api/app/models/grid.py` defines the two database tables.
- `apps/web/src/app/(dashboard)/grid/page.tsx` is the `/grid` overview;
  `apps/web/src/app/(dashboard)/grid/[zone]/page.tsx` is the zone detail page.
- `apps/web/src/components/grid/` contains the map, driver bars, and charts.

## Price sources

The engine tracks eight ERCOT load zones from `app/grid/zones.py`, plus
`HB_HUBAVG` as the system-wide comparison price. RT prices have 15-minute
intervals; DA prices have hourly intervals. Both are stored in $/MWh.

- **Historical backfill:** public ERCOT yearly *Historical RTM Load Zone and
  Hub Prices* (MIS report 13061) and *Historical DAM Load Zone and Hub Prices*
  (MIS report 13060) files. These downloads need no authentication. The
  current-year files are refreshed roughly weekly.
- **Recent days:** the ERCOT Public API supplies prices beyond the yearly
  files. Put `ERCOT_USERNAME`, `ERCOT_PASSWORD`, and `ERCOT_PRIMARY_KEY` in
  the repo-root `.env`; `ERCOT_SECONDARY_KEY` is optional. Subscription keys
  alone are insufficient: the client obtains an `id_token` with the username
  and password, then sends that token and a subscription key with requests.

Both parsers keep only the tracked zones and hub. ERCOT's local delivery times
are converted to UTC before storage. The `Repeated Hour Flag` in historical
files and `DSTFlag` in API data distinguish the repeated fall-back hour;
that second hour is interpreted as standard time.

## Tables

- `grid_prices`: one RT or DA settlement-point price per interval, keyed by
  `(settlement_point, market, interval_start)`. Backfill and update upsert
  on this key. `interval_start` is timezone-aware UTC; `price` is $/MWh.
- `grid_zone_metrics`: one latest computed row per load zone, overwritten
  on each compute run. It stores the analysis window, composite score,
  raw `metrics`, normalized `scores`, chart `series` (JSONB), and
  `computed_at`. The hub has prices but no zone-metrics row.

Schema changes use Alembic; see [database.md](database.md).

## CLI

Run from `apps/api` with the database available:

```bash
uv run python -m app.grid backfill 2025 2026  # both RT and DA yearly files
uv run python -m app.grid update               # recent RT and DA via Public API
uv run python -m app.grid compute              # recompute metrics and scores
```

`backfill` treats each year argument separately. `update` starts at the last
stored day for each market to repair partial days; without stored prices it
starts seven days back. Neither command recomputes the zone scores.

Run `compute` after backfill or update, and after changing assumptions in
`app/grid/config.py`. It uses the trailing 365 days ending at the latest RT
interval, then upserts the eight zone snapshots. It does not fetch prices.

## Drivers and score

Five raw metrics become 0–100 driver scores. Defaults and weights live in
`app/grid/config.py`, not `.env`.

| Driver | Weight | Raw metric |
| --- | ---: | --- |
| Battery arbitrage | 40% | Daily battery backtest value, annualized to $/battery/year. |
| Congestion premium | 20% | Mean of `max(zone RT − HB_HUBAVG RT, 0)` over aligned intervals, $/MWh. |
| Scarcity hours | 15% | RT intervals at or above $1,000/MWh, converted to hours and annualized. |
| Grid surprise | 15% | Mean absolute difference between hourly averaged RT and aligned DA prices, $/MWh. |
| Negative prices | 10% | Percent of RT intervals with price strictly below $0/MWh. |

Annualized metrics scale the observed span to 365 days. The engine also
calculates context metrics, including average RT price, volatility, typical
daily spread, signed average basis, and the share of arbitrage value from the
top ten days; these do not enter the score.

Each driver is min-max normalized **across the eight load zones**: the
lowest raw value scores 0 and the highest scores 100. A tie across every
zone scores 50. The Grid Value Score is their weighted mean (weights are
normalized at use). Scores and ranks are relative to this set of zones and
can change when the comparison data or assumptions change.

## Battery backtest

For each America/Chicago calendar day, `backtest_daily` uses dynamic
programming over battery state of charge to find the best charge/discharge
sequence with perfect knowledge of that day's RT prices. It starts and
ends each day empty, moves at most one 15-minute power step per interval,
and applies round-trip efficiency as a charging loss.

The modeled battery defaults to 39.2 kWh capacity, 11.5 kW power, and 90%
round-trip efficiency. These are analysis assumptions in
`app/grid/config.py`, not published battery specifications. The backtest is
a perfect-foresight historical upper bound for screening, not a P&L forecast.

## Battery value per lead size

`compute` also backtests the battery sizes we pitch to leads (`LEAD_BATTERIES_KW` in `app/grid/config.py`: 25/40/50 kWh at an assumed ~0.46 kW per kWh) and stores `battery_value_<kWh>` ($/yr) in each zone's `metrics`. Lead scoring reads these; see [residential-leads.md](residential-leads.md).

## API and map

- `GET /grid/zones` returns scored zone summaries in descending rank.
- `GET /grid/zones/{code}` adds the analysis period, raw metrics, chart
  series, and current assumptions; unknown codes return 404.

The zone shapes live in `apps/api/app/grid/ercot-zones.geojson`, served at `GET /grid/zones.geojson` (web map) and used to place leads in a zone. Rebuild it from
`apps/api` with `uv run python scripts/build_zone_geojson.py` if its source
geometry needs refreshing; the script writes that file.

The script uses an ArcGIS Online ERCOT Load Zones layer (ICF, 2022) for
Houston, North, South, and West, and HIFLD Electric Retail Service
Territories for Austin Energy and CPS Energy. It simplifies coordinates
to keep the file small. These boundaries are approximate. `LZ_LCRA` and
`LZ_RAYBN` have no contiguous mapped shape, but remain in scoring and lists.

Prices and scores resolve to load zones, not streets or addresses. Do not
make street-level claims from these values or the approximate map geometry.
