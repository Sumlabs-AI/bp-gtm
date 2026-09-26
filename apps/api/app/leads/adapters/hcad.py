"""Read Harris Central Appraisal District's real-property CAMA ZIP exports.

The owner, residential-building, and exemption archives are published per tax year at
https://download.hcad.org/data/CAMA/<year>/. For accounts with several residential
buildings, use the one with the largest heated area; im_sq_ft is base area, not
heated area. HCAD does not publish a confidentiality flag in these files, so the
exact owner placeholder CURRENT OWNER is treated as protected.
"""

from datetime import date
from pathlib import Path
from zipfile import ZipFile

import httpx
import pandas as pd

from app.leads.frames import PROPERTY_COLUMNS as _PROPERTY_COLUMNS

SOURCE_ID: str = "hcad_harris_cama_2026"

_BASE_URL = "https://download.hcad.org/data/CAMA/{year}"
_ARCHIVES = (
    ("Real_acct_owner.zip", "real_acct.txt"),
    ("Real_building_land.zip", "building_res.txt"),
    ("Real_jur_exempt.zip", "jur_exempt_cd.txt"),
)
_REDACTED_OWNERS = {"CURRENT OWNER", "CONFIDENTIAL", "CONFIDENTIAL OWNER"}
_FIXTURES = {"RMB": "bedrooms", "RMF": "full_baths", "RMH": "half_baths", "STY": "stories"}


def _base_url(client: httpx.Client) -> str:
    """Current tax year's folder, or last year's until HCAD publishes the new one."""
    for year in (date.today().year, date.today().year - 1):
        url = _BASE_URL.format(year=year)
        if client.head(f"{url}/{_ARCHIVES[0][0]}").status_code == 200:
            return url
    raise ValueError("No HCAD CAMA export found for this or last year")


def fingerprint() -> str:
    """Combine the three ZIPs' HTTP version headers without downloading their bodies."""
    versions = []
    with httpx.Client(follow_redirects=True, timeout=30) as client:
        base = _base_url(client)
        for filename, _ in _ARCHIVES:
            response = client.head(f"{base}/{filename}")
            response.raise_for_status()
            headers = response.headers
            versions.append(
                f"{base}/{filename}:{headers.get('last-modified', '')}:"
                f"{headers.get('etag', '')}:{headers.get('content-length', '')}"
            )
    return "|".join(versions)


def fetch(raw_dir: Path) -> list[Path]:
    """Stream the three original HCAD ZIPs into an existing directory."""
    paths = []
    with httpx.Client(follow_redirects=True, timeout=300) as client:
        base = _base_url(client)
        for filename, _ in _ARCHIVES:
            path = raw_dir / filename
            with client.stream("GET", f"{base}/{filename}") as response:
                response.raise_for_status()
                with path.open("wb") as output:
                    for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                        output.write(chunk)
            paths.append(path)
    return paths


def _read(path: Path, member: str, columns: list[str]) -> pd.DataFrame:
    with ZipFile(path) as archive, archive.open(member) as source:
        return pd.read_csv(
            source,
            sep="\t",
            encoding="cp1252",
            dtype=str,
            keep_default_na=False,
            usecols=columns,
        )


def _mail_address(
    street: str, line2: str, city: str, state: str, postal: str, country: str
) -> str | None:
    locality = " ".join(part for part in (state, postal) if part)
    return ", ".join(part for part in (street, line2, city, locality, country) if part) or None


def parse(paths: list[Path]) -> pd.DataFrame:
    """Join ZIP members by account into one canonical row per real-property account."""
    archives = {path.name: path for path in paths}
    owner = _read(
        archives["Real_acct_owner.zip"],
        "real_acct.txt",
        [
            "acct",
            "mailto",
            "mail_addr_1",
            "mail_addr_2",
            "mail_city",
            "mail_state",
            "mail_zip",
            "mail_country",
            "site_addr_1",
            "site_addr_2",
            "site_addr_3",
            "state_class",
            "tot_mkt_val",
        ],
    )
    for column in owner.columns:
        owner[column] = owner[column].str.strip()

    exempt = _read(archives["Real_jur_exempt.zip"], "jur_exempt_cd.txt", ["acct", "exempt_cat"])
    exempt["acct"] = exempt["acct"].str.strip()
    homestead_accounts = exempt.loc[
        exempt["exempt_cat"].str.contains(r"(?:^|\s)(?:RES|PAR)(?:\s|$)", regex=True),
        "acct",
    ]
    del exempt

    buildings = _read(
        archives["Real_building_land.zip"],
        "building_res.txt",
        ["acct", "bld_num", "heat_ar", "date_erected"],
    )
    buildings["acct"] = buildings["acct"].str.strip()
    buildings["bld_num"] = pd.to_numeric(buildings["bld_num"], errors="coerce")
    buildings["heat_ar"] = pd.to_numeric(buildings["heat_ar"], errors="coerce")
    buildings["date_erected"] = pd.to_numeric(buildings["date_erected"], errors="coerce")
    buildings = (
        buildings.sort_values(
            ["acct", "heat_ar", "bld_num"], ascending=[True, False, True], na_position="last"
        )
        .drop_duplicates("acct")
        .set_index("acct")[["bld_num", "heat_ar", "date_erected"]]
    )

    # Room counts and stories of that same building (fixtures: RMB bedrooms, RMF/RMH full/half
    # baths, STY stories).
    fixtures = _read(
        archives["Real_building_land.zip"], "fixtures.txt", ["acct", "bld_num", "type", "units"]
    )
    fixtures = fixtures[fixtures["type"].str.strip().isin(_FIXTURES)]
    fixtures = fixtures.assign(
        acct=fixtures["acct"].str.strip(),
        bld_num=pd.to_numeric(fixtures["bld_num"], errors="coerce"),
        type=fixtures["type"].str.strip().map(_FIXTURES),
        units=pd.to_numeric(fixtures["units"], errors="coerce"),
    )
    fixtures = fixtures.merge(
        buildings["bld_num"].reset_index(), on=["acct", "bld_num"]
    ).pivot_table(index="acct", columns="type", values="units", aggfunc="first")
    buildings = buildings.join(fixtures.reindex(columns=list(_FIXTURES.values())))

    # Extra features: solar PV (any "Solar ..." description) and residential pools/spas
    # (codes RRP*), a proxy for a large electric load.
    features = _read(
        archives["Real_building_land.zip"], "extra_features.txt", ["acct", "cd", "l_dscr"]
    )
    features["acct"] = features["acct"].str.strip()
    solar_accounts = features.loc[features["l_dscr"].str.contains("solar", case=False), "acct"]
    pool_accounts = features.loc[features["cd"].str.strip().str.startswith("RRP"), "acct"]
    del features

    confidential = owner["mailto"].str.upper().isin(_REDACTED_OWNERS)
    mail_addresses = [
        None if protected else _mail_address(street, line2, city, state, postal, country)
        for protected, street, line2, city, state, postal, country in zip(
            confidential,
            owner["mail_addr_1"],
            owner["mail_addr_2"],
            owner["mail_city"],
            owner["mail_state"],
            owner["mail_zip"],
            owner["mail_country"],
            strict=True,
        )
    ]
    properties = pd.DataFrame(
        {
            "county": "harris",
            "account": owner["acct"],
            "situs_address": owner["site_addr_1"].replace("", None),
            "situs_city": owner["site_addr_2"].replace("", None),
            "situs_zip": owner["site_addr_3"].where(
                owner["site_addr_3"].str.fullmatch(r"\d{5}"), None
            ),
            "owner_name": owner["mailto"].replace("", None).mask(confidential),
            "mail_address": mail_addresses,
            "state_class": owner["state_class"].replace("", None),
            "is_single_family": owner["state_class"].eq("A1"),
            "homestead": owner["acct"].isin(homestead_accounts),
            "confidential": confidential,
            "market_value": pd.to_numeric(owner["tot_mkt_val"], errors="coerce").astype(float),
            "has_solar": owner["acct"].isin(solar_accounts),
            "has_pool": owner["acct"].isin(pool_accounts),
        }
    )
    del owner, homestead_accounts, mail_addresses
    result = properties.join(buildings, on="account").rename(
        columns={"heat_ar": "heated_sqft", "date_erected": "year_built"}
    )
    for column in ("owner_name", "mail_address"):
        result[column] = result[column].astype(object).where(result[column].notna(), None)
    result["heated_sqft"] = result["heated_sqft"].astype(float)
    result["year_built"] = (
        result["year_built"]
        .where(result["year_built"].between(1800, date.today().year + 1))
        .astype("Int64")
    )
    for column in ("bedrooms", "full_baths", "half_baths"):
        result[column] = result[column].round().astype("Int64")
    result["stories"] = result["stories"].where(result["stories"] > 0).astype(float)
    return result[_PROPERTY_COLUMNS]
