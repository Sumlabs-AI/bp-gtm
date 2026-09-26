"""Canonical frames that every source adapter must return.

Adapters (app/leads/adapters/*.py) turn raw upstream files into a pandas DataFrame with
exactly these columns. Loaders in app/leads/store.py add the normalized address key.
Use None/NaN for unknown values; never invent them.
"""

# One row per appraisal account (a property). Source: county appraisal districts.
PROPERTY_COLUMNS = [
    "county",  # lowercase county name, e.g. "harris"
    "account",  # appraisal account id (string, keep leading zeros)
    "situs_address",  # street address of the property, e.g. "123 N OAK ST"
    "situs_city",
    "situs_zip",  # 5-digit string
    "owner_name",
    "mail_address",  # full mailing address as one string
    "state_class",  # Texas PTAD state property class code, e.g. "A1"
    "is_single_family",  # bool: state class A1 (single-family residence)
    "homestead",  # bool: has a residence homestead exemption (owner-occupied)
    "confidential",  # bool: owner withheld under Texas Tax Code 25.025
    "market_value",  # float, USD
    "heated_sqft",  # float, conditioned living area
    "year_built",  # int
    "has_solar",  # bool: appraisal record lists solar PV panels
    "has_pool",  # bool: residential pool/spa on the appraisal record (a large electric load)
]

# One row per parcel: where the property is. Source: county parcel GIS layers.
PARCEL_COLUMNS = [
    "county",
    "account",  # same appraisal account id as PROPERTY_COLUMNS
    "lat",  # WGS84 point inside the parcel (not necessarily the centroid)
    "lon",
]

# One row per ESI ID (electric service point / meter). Source: ERCOT TDSP ESI ID extract.
METER_COLUMNS = [
    "esiid",
    "tdsp",  # "centerpoint", "oncor", ... (mapped from DUNS)
    "address",
    "city",
    "zip",  # 5-digit string
    "county",  # lowercase
    "premise_type",  # "residential", "small_non_residential", "large_non_residential", ...
    "status",  # "active" | "inactive" | "de_energized" ...
    "published_at",  # tz-aware datetime of the ERCOT document the row came from
]

# One row per permit. Sources: city/county permit feeds.
PERMIT_COLUMNS = [
    "source",  # adapter id, e.g. "harris_county_permits"
    "permit_id",
    "address",
    "city",
    "zip",  # 5-digit string or None
    "issued_date",  # date
    "category",  # "solar" | "ev_charger" | "new_home" | "other"
    "description",  # raw permit name/type/comments used for the category
    "lat",  # float or None
    "lon",  # float or None
]

PERMIT_CATEGORIES = {"solar", "ev_charger", "new_home", "other"}
