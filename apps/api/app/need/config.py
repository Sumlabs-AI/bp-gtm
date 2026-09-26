"""Need Engine settings. Not secrets, so they live in code (like app/grid/config.py)."""

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


class LiveWeatherConfig(BaseModel):
    """Live Weather Signals from NWS alerts (M4B-1). No score yet."""

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


live_weather = LiveWeatherConfig()
