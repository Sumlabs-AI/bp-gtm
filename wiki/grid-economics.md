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
| Battery arbitrage | 40% | Realistic battery value (day-ahead planner, below), annualized to $/battery/year. |
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

`app/grid/dispatch.py` runs two backtests on the same battery physics, adapted
from [WattGap](https://github.com/saivarun3407/wattgap) (MIT, see
`app/grid/LICENSE-wattgap`):

- **Realistic value (`simulate`)**: a day-ahead planner that uses no hindsight.
  Each local day it picks its charge hours (the cheapest day-ahead hours) and
  discharge hours (the most expensive) from that day's DA prices, which ERCOT
  publishes the afternoon before. Window lengths are the whole hours a full
  charge or discharge takes at full power. It plans nothing when the DA spread
  doesn't cover losses and wear. Inside the windows it follows the RT price:
  it charges only if RT is cheap enough to pay back and sells only above
  breakeven. Outside them it sells at full power when RT beats the day's top
  DA price by `PlannerConfig.spike_multiple` (1.25, WattGap's value). Charge
  carries over from day to day. A test checks that later prices never change
  earlier results.
- **Ceiling (`ceiling`)**: the most any battery with the same physics could
  have earned with perfect knowledge of every RT price, as one linear program
  over the whole window (scipy HiGHS). The realistic value can't exceed it.

Shared physics: each of charging and discharging loses √(round-trip
efficiency); `reserve_soc` (20%) of capacity is kept as the member's backup
and never sold; `wear_usd_per_kwh` ($0.02) is charged per kWh discharged; the
battery starts at its reserve and leftover energy is worth nothing. The zone
battery defaults to 39.2 kWh / 11.5 kW / 90%. These are analysis assumptions
in `app/grid/config.py`, not published battery specifications.

The realistic value is still a screening estimate, not a P&L forecast: energy
only (no ancillary services, retail margin or fees), load-zone prices, price
taker. On 2025 prices it earned about 50% of the ceiling in Houston, North
and West, in line with WattGap's measured 48–63% across 2019–2025.

## Battery value per lead size

`compute` also values the battery sizes we pitch to leads (`LEAD_BATTERIES_KW` in `app/grid/config.py`: 25/40/50 kWh at an assumed ~0.46 kW per kWh). Each zone's `metrics` stores `battery_value_<kWh>` (realistic, last 365 days) and `battery_ceiling_<kWh>` ($/yr), and `series.battery_years` holds the realistic value (`"25"`, …) and ceiling (`"ceiling_25"`, …) per full past calendar year (as far back as prices are loaded; `backfill 2019 … 2024` for the full history). Leads are valued on the average of those years. `compute` runs one ceiling LP per zone, size and year (~2–3 min with 2019–2025 loaded). Lead scoring reads these; see [residential-leads.md](residential-leads.md).

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
