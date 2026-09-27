"""ACS 5-year tables pulled for block-group Fit features, and where to get them.

Source: Census "table-based summary files" (one pipe-delimited file per table, every geography,
estimates + MOEs). No API key needed, unlike api.census.gov. Line numbers follow
documentation/ACS<vintage>5YR_Table_Shells.txt.
"""
from __future__ import annotations

SF_URL = ("https://www2.census.gov/programs-surveys/acs/summary_file/{vintage}/table-based-SF/"
          "data/5YRData/acsdt5y{vintage}-{table}.dat")
SHELLS_URL = ("https://www2.census.gov/programs-surveys/acs/summary_file/{vintage}/table-based-SF/"
              "documentation/ACS{vintage}5YR_Table_Shells.txt")

STATE_FIPS = "48"
# GEO_ID prefixes kept from the national files (summary level + "US" + state).
GEO_PREFIX = {"bg": f"1500000US{STATE_FIPS}", "tract": f"1400000US{STATE_FIPS}"}

# table -> what we use it for
TABLES = {
    "B01003": "total population",
    "B25001": "housing units (density, exposure)",
    "B25002": "occupancy status (vacancy rate)",
    "B25004": "vacancy status (seasonal homes)",
    "B25003": "tenure (% owner-occupied)",
    "B25024": "units in structure (% single-family detached)",
    "B25032": "tenure by units in structure (owner-occupied single-family detached = eligible homes)",
    "B25077": "median home value",
    "B19013": "median household income",
    "B25035": "median year built",
    "B25034": "year built distribution (% built before 1980)",
    "B11007": "households with someone 65+",
    "B25039": "median year householder moved in (by tenure)",
    "B25038": "tenure by year moved in (long-tenure owners)",
    "B25040": "house heating fuel",
    "B25117": "tenure by house heating fuel (owners on electric heat)",
    "B08301": "means of transportation to work (work from home)",
    "B25081": "mortgage status",
    "B25018": "median rooms",
    "B25041": "bedrooms",
    "B25010": "average household size (by tenure)",
    "B11005": "households with children under 18",
    "B25092": "median owner costs as % of income",
    "B25091": "owner costs as % of income, distribution (cost burden)",
}

# Estimates at or below this are Census annotation codes, not values
# (-666666666 not computed, -999999999 too few cases, -888888888 not applicable, ...).
SENTINEL_MAX = -111_111_111
# MOE codes: -555555555 = controlled estimate (MOE is 0); -333333333 / -222222222 = median falls in
# an open-ended interval / MOE not computed.
MOE_CONTROLLED = -555_555_555
MOE_OPEN_ENDED = -333_333_333
