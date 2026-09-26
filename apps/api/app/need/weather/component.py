"""The Weather Need Component of a Cell (Baseline): Storm Exposure from its res-6 parent
and Temperature Extremes Exposure from its county, each a Texas percentile.

Placeholder formula (equal weights, provisional): the mean of the sub-scores that exist.
Tropical and ice events are not in Baseline Weather; they show up through outage history
and, later, Live Weather.
"""

from sqlalchemy.orm import Session

from app import geo
from app.models import Cell, CountyTemperatureFeatures, StormExposure
from app.need.components import mean_of_present
from app.need.weather.store import load_features
from app.need.weather.storms import RESOLUTION
from app.need.weather.temperature import LIMITATION

NO_STORM = "No Storm Exposure for this area: score uses Temperature Extremes Exposure only"
NO_TEMPERATURE = "No temperature data for this county: score uses Storm Exposure only"
OFFICE_CAVEAT = (
    "Warning issuance varies by NWS office; Houston (HGX) issues ~25% more warning-days per "
    "severe report than the Texas median."
)


def _storm(s: StormExposure) -> dict:
    return {
        "score": s.storm_exposure,
        # Provenance: the ~36 km² res-6 cell this value belongs to, not the res-8 Cell.
        "resolution": s.resolution,
        "sourceCell": s.h3_index,
        "source": "NWS warnings via Iowa Environmental Mesonet (public domain)",
        "dataThrough": s.data_through.isoformat(),
        "metrics": {
            "warningDays5y": s.warning_days_5y,
            "warningDays365d": s.warning_days_365d,
            "severeThunderstormWarnings5y": s.severe_thunderstorm_warnings_5y,
            "tornadoWarnings5y": s.tornado_warnings_5y,
            "extremeWindWarnings5y": s.extreme_wind_warnings_5y,
        },
        "percentile": s.storm_exposure,
        "caveats": [OFFICE_CAVEAT],
    }


def _temperature(t: CountyTemperatureFeatures) -> dict:
    return {
        "score": t.temperature_exposure,
        "county": {"fips": t.county_fips},
        "source": "NOAA nClimGrid-daily, county averages (public domain)",
        "dataThrough": t.data_through.isoformat(),
        "metrics": {
            "heatDays100F5y": t.heat_days_100f_5y,
            "heatDays95F5y": t.heat_days_95f_5y,
            "coldDays28F5y": t.cold_days_28f_5y,
            "coldDays32F5y": t.cold_days_32f_5y,
            "heatDays100F365d": t.heat_days_100f_365d,
            "coldDays28F365d": t.cold_days_28f_365d,
        },
        # Scored: >= 100°F and <= 28°F days. The 95°F / 32°F counts are context.
        "percentiles": {"heatDays100F5y": t.heat_100f_pctl, "coldDays28F5y": t.cold_28f_pctl},
        "limitations": [LIMITATION],
    }


def weather_components(db: Session, cells: list[Cell]) -> dict[str, dict | None]:
    """h3_index -> Weather Need Component detail (None when neither sub-score has data).
    One query per table, whatever the number of Cells."""
    parents = {c.h3_index: geo.cell_to_parent(c.h3_index, RESOLUTION) for c in cells}
    storms, temps = load_features(
        db, set(parents.values()), {c.county_fips for c in cells if c.county_fips}
    )
    result: dict[str, dict | None] = {}
    for cell in cells:
        s = storms.get(parents[cell.h3_index])
        t = temps.get(cell.county_fips)
        if s is None and t is None:
            result[cell.h3_index] = None
            continue
        storm = _storm(s) if s else None
        temperature = _temperature(t) if t else None
        storm_score = storm["score"] if storm else None
        temperature_score = temperature["score"] if temperature else None
        notes = []
        if storm_score is None:
            notes.append(NO_STORM)
        if temperature_score is None:
            notes.append(NO_TEMPERATURE)
        result[cell.h3_index] = {
            "score": mean_of_present(storm_score, temperature_score),
            "stormExposure": storm,
            "temperatureExtremesExposure": temperature,
            "notes": notes,
        }
    return result
