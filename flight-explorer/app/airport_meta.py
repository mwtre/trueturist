"""IATA metadata (country) for route filtering (domestic vs EU vs non-EU)."""

from __future__ import annotations

import airportsdata

_IATA: dict = airportsdata.load("IATA")

# EU member states (ISO 3166-1 alpha-2), 27 countries post-Brexit. Used for “non-EU only” filtering.
# United Kingdom + Crown Dependencies (ISO 3166-1 alpha-2) for “exclude UK”.
UK_AREA_COUNTRIES: frozenset[str] = frozenset({"GB", "GG", "JE", "IM"})

EU_MEMBER_COUNTRIES: frozenset[str] = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DK",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "HU",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SK",
        "SI",
        "ES",
        "SE",
    }
)


def country_code_for_iata(code: str) -> str | None:
    rec = _IATA.get(code.upper())
    if not rec:
        return None
    c = rec.get("country")
    return str(c) if c else None


def airport_city_for_iata(code: str) -> str | None:
    """Municipality served (often matches the main Wikipedia city article with landmark photos)."""
    rec = _IATA.get(code.upper())
    if not rec:
        return None
    c = rec.get("city")
    if not c:
        return None
    s = str(c).strip()
    return s or None


def airport_subd_for_iata(code: str) -> str | None:
    rec = _IATA.get(code.upper())
    if not rec:
        return None
    s = rec.get("subd")
    if not s:
        return None
    t = str(s).strip()
    return t or None


def is_international_leg(origin_iata: str, dest_iata: str) -> bool:
    """True if origin and destination are in different countries.

    If country data is missing for either airport, the route is treated as cross-border
    so we do not drop results on incomplete metadata.
    """
    o = country_code_for_iata(origin_iata)
    d = country_code_for_iata(dest_iata)
    if not o or not d:
        return True
    return o != d


def is_eu_country(iso_cc: str) -> bool:
    return iso_cc.upper() in EU_MEMBER_COUNTRIES


def destination_outside_eu(dest_iata: str) -> bool:
    """True if the destination airport’s country is known and not an EU member.

    Unknown country: False (strict, so “non-EU only” does not accidentally include uncertain hubs).
    """
    d = country_code_for_iata(dest_iata)
    if not d:
        return False
    return not is_eu_country(d)


def destination_in_eu(dest_iata: str) -> bool:
    """True if the destination airport’s country is an EU member (27).

    Unknown country: False (strict for “EU only” scans).
    """
    d = country_code_for_iata(dest_iata)
    if not d:
        return False
    return is_eu_country(d)


def destination_in_uk_area(dest_iata: str) -> bool:
    """True if destination is in the UK or Crown Dependencies (GB, GG, JE, IM)."""
    d = country_code_for_iata(dest_iata)
    if not d:
        return False
    return d.upper() in UK_AREA_COUNTRIES
