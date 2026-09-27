"""Need Engine settings. Not secrets, so they live in code (like app/grid/config.py)."""

from typing import Literal

from pydantic import BaseModel

from app import geo
from app.need.outage.events import EventRules


class ExposureConfig(BaseModel):
    window_years: int = 5
    # A county joins the Reference Population when EAGLE-I has rows for it in at least this
    # share of the window's calendar years (ORNL publishes coverage per state, not county).
    min_years_share: float = 0.8


class NeedConfig(BaseModel):
    # Resolution Cells are seeded at. Changing it means re-seeding (cells keep their own).
    h3_resolution: int = geo.RESOLUTION
    # Safety cap for GET /need/cells; the map also hides Cells when zoomed out.
    viewport_max_cells: int = 20_000


need = NeedConfig()

# Baseline Outage Need (re-run `python -m app.need outage compute` after changing them).
outage_events = EventRules()
outage_exposure = ExposureConfig()

# Cell -> EIA utility id from data we already have (no licensed territory layer):
# Austin Energy's territory is LZ_AEN; Harris County is CenterPoint. Anything else: unknown.
UTILITY_BY_LOAD_ZONE = {"LZ_AEN": 1015}  # Austin Energy
UTILITY_BY_COUNTY = {"48201": 8901}  # CenterPoint Energy (Harris)


class WeatherConfig(BaseModel):
    """Baseline Weather Need. Re-run `python -m app.need weather compute` after changing."""

    window_years: int = 5
    # Measured temperature thresholds (°F): scored, and context-only.
    heat_f: float = 100
    cold_f: float = 28
    heat_context_f: float = 95
    cold_context_f: float = 32
    # Known issuance practice by NWS office (from the 2021-2025 warning vs SPC report check).
    office_notes: dict[str, str] = {
        "HGX": "Houston (HGX) issues ~25% more warning-days per severe report than the Texas "
        "median, so this Storm Exposure may read high."
    }


weather = WeatherConfig()


class NwsAlertConfig(BaseModel):
    """NWS Alerts (M4B-1): official alerts, observed and not scored."""

    alerts_url: str = "https://api.weather.gov/alerts/active?area=TX"
    user_agent: str = "base-power-gtm need engine (github.com/mamalovesyou/bp-gtm)"
    refresh_minutes: int = 5
    # With no successful Snapshot for this long, live data is reported stale.
    stale_after_minutes: int = 30
    # NWS event -> category. Anything else (flood, fire, air quality, marine) is ignored.
    categories: dict[str, str] = {
        "Tornado Warning": "tornado",
        "Tornado Watch": "tornado",
        "Severe Thunderstorm Warning": "severe_storm",
        "Severe Thunderstorm Watch": "severe_storm",
        "Extreme Wind Warning": "severe_storm",
        "Hurricane Warning": "tropical",
        "Hurricane Watch": "tropical",
        "Tropical Storm Warning": "tropical",
        "Tropical Storm Watch": "tropical",
        "Storm Surge Warning": "tropical",
        "Ice Storm Warning": "winter",
        "Winter Storm Warning": "winter",
        "Winter Storm Watch": "winter",
        "Extreme Heat Warning": "heat",
        "Extreme Heat Watch": "heat",
        "Heat Advisory": "heat",
        "Extreme Cold Warning": "cold",
        "Extreme Cold Watch": "cold",
        "Cold Weather Advisory": "cold",
        "Hard Freeze Warning": "cold",
        "Freeze Warning": "cold",
    }
    # Most severe first: which category a Cell reports when several are active.
    category_order: list[str] = ["tornado", "tropical", "severe_storm", "winter", "cold", "heat"]


nws_alerts = NwsAlertConfig()


class ForecastCondition(BaseModel):
    variable: str  # NWS gridpoint layer
    nws_uom: str  # the unit NWS must send it in (checked, so a change can't go unnoticed)
    direction: Literal["ge", "le"]  # "ge": at or above is dangerous; "le": at or below
    elevated: float  # in `unit`
    high: float
    unit: str
    per_interval: bool = False  # judge each forecast interval (accumulations), not hours


class ForecastConfig(BaseModel):
    """Forecast Signals (M4B-2): our reading of NWS grid forecasts and SPC outlooks.
    Fixed Texas-wide thresholds (not office-relative). No score yet."""

    horizon_hours: int = 48  # Active: starting within this many hours
    # Stored further ahead, so an unchanged NWS forecast needn't be re-read every hour.
    storage_horizon_hours: int = 72
    refresh_minutes: int = 60
    stale_after_hours: int = 3
    resolution: int = 6  # one forecast point per res-6 cell covering the Markets
    conditions: dict[str, ForecastCondition] = {
        "wind": ForecastCondition(
            variable="windGust",
            nws_uom="wmoUnit:km_h-1",
            direction="ge",
            elevated=46,
            high=58,
            unit="mph",
        ),
        "heat": ForecastCondition(
            variable="heatIndex",
            nws_uom="wmoUnit:degC",
            direction="ge",
            elevated=105,
            high=110,
            unit="°F",
        ),
        "cold": ForecastCondition(
            variable="temperature",
            nws_uom="wmoUnit:degC",
            direction="le",
            elevated=28,
            high=20,
            unit="°F",
        ),
        "ice": ForecastCondition(
            variable="iceAccumulation",
            nws_uom="wmoUnit:mm",
            direction="ge",
            elevated=0.1,
            high=0.25,
            unit="in",
            per_interval=True,
        ),
    }
    spc_urls: list[str] = [
        "https://www.spc.noaa.gov/products/outlook/day1otlk_cat.lyr.geojson",
        "https://www.spc.noaa.gov/products/outlook/day2otlk_cat.lyr.geojson",
    ]
    # SPC categorical risk -> level, lowest risk first (the order ranks them). Marginal and
    # general thunder are not signals.
    spc_levels: dict[str, str] = {"SLGT": "elevated", "ENH": "high", "MDT": "high", "HIGH": "high"}
    level_order: list[str] = ["high", "elevated"]  # most severe first


forecast = ForecastConfig()


class GridLiveConfig(BaseModel):
    """Live grid inputs (M5): ERCOT Grid Condition + our Grid Stress Signals. No score."""

    # Our reliability thresholds (MW). ERCOT's own EEA1 trigger is PRC < 2,500 MW.
    prc_low_mw: int = 3000
    margin_low_mw: int = 3000
    # Market spikes use the existing scarcity price (app.grid.config.ScoringConfig).
    condition_stale_minutes: int = 20
    price_stale_minutes: int = 45
    refresh_minutes: int = 5  # dashboards
    price_refresh_minutes: int = 15  # MIS RT report
    rt_documents: int = 4  # re-read the last hour of 15-min files each time (fills gaps)
    dam_documents: int = 2
    dam_refresh_minutes: int = 60  # picks up the daily ~12:35 publication


grid_live = GridLiveConfig()


class BaselineConfig(BaseModel):
    """Baseline Need (M6). Re-run `python -m app.need baseline compute` after changing."""

    # Inputs within this many points: the Dominant Driver is "both".
    driver_margin: float = 10.0


baseline = BaselineConfig()


class OpportunityConfig(BaseModel):
    """Opportunity Score weights (app/need/opportunity.py). Computed on read: no re-run."""

    # From the project plan (ml/base_gtm_ml_plan.txt §9): who buys counts more than how
    # needed it is. Must sum to 1 so the score stays on 0-100.
    propensity_weight: float = 0.6
    need_weight: float = 0.4
    # Lead Cells: the highest-Opportunity Cells of each county, whole Cells, until they hold
    # this share of the county's eligible homes (0.1% gives ~900 in Harris + Travis).
    # Per county because Baseline Need is a Texas percentile: one fixed score leaves Austin out.
    lead_share: float = 0.001


opportunity = OpportunityConfig()


class TimingConfig(BaseModel):
    """Timing multiplier (app/need/timing.py): when to knock, from NWS Alert history.

    Shape from backup-permit research in Austin/San Antonio (Uri 2021, Feb 2023 ice storm):
    permits rise within 2 weeks of a storm and peak 4-8 weeks after it; buying decisions come
    2-4 weeks before the permit. A major event (Uri) lifted demand for months. Two events and
    two cities: a shape to follow, not a fitted curve.
    """

    # An alert covering the Cell that is in effect now or takes effect within this many hours.
    pre_event_hours: int = 72
    pre_event: float = 1.1  # a "get ready" talk track; not when people buy
    peak: float = 1.5  # the post-event buying window
    # Days after the event ends: full `peak` until peak_days, then linear down to 1.0 at
    # fade_days.
    peak_days: int = 28
    fade_days: int = 56
    major_peak_days: int = 56
    major_fade_days: int = 180
    # NWS events that open a post-event window. Watches and advisories don't (nothing may
    # have happened); plain Freeze Warnings and heat alerts rarely cut power.
    major_events: list[str] = [
        "Ice Storm Warning",
        "Winter Storm Warning",
        "Extreme Cold Warning",
        "Hurricane Warning",
    ]
    events: list[str] = [
        "Tornado Warning",
        "Severe Thunderstorm Warning",
        "Extreme Wind Warning",
        "Tropical Storm Warning",
        "Hard Freeze Warning",
    ]


timing = TimingConfig()


# Version of the Need feature definitions (columns, thresholds, windows, sources) that the
# ML exports carry and a Propensity file records. Bump it when a definition changes; the
# changelog lives in wiki/ml-contract.md.
FEATURE_VERSION = "1.0.0"


# Baseline Need bands, shared by the map legend, the lead filters and the API. Lower edge
# inclusive, upper exclusive, except the top band, which includes 100.
NEED_BANDS: dict[str, tuple[float, float]] = {
    "0-40": (0, 40),
    "40-60": (40, 60),
    "60-80": (60, 80),
    "80-100": (80, 100),
}
NEED_BANDS_TOP = "80-100"
