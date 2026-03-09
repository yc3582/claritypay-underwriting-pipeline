"""
Client for REST Countries API: fetch -> parse -> validate.

Enriches merchant country names with region and subregion data.
Uses in-memory caching so each unique country is only fetched once.
"""

import logging

import httpx
from pydantic import ValidationError

from ingestion.validators import CountryInfo

logger = logging.getLogger(__name__)

BASE_URL = "https://restcountries.com/v3.1"

# In-memory cache: country_name -> CountryInfo
# Avoids repeated API calls for the same country (e.g. 26 UK merchants = 1 call)
_cache: dict[str, CountryInfo] = {}


def fetch_country(country_name: str) -> dict | None:
    """
    Fetch: Call REST Countries API for a single country.

    Uses the /name/{country} endpoint with fullText=true so
    "United Kingdom" matches exactly, not partial matches like
    "United States" or "United Arab Emirates".

    Returns the first result as a dict, or None if the call fails.
    """
    url = f"{BASE_URL}/name/{country_name}"
    logger.info(f"Fetching country data for: {country_name}")

    try:
        response = httpx.get(
            url,
            params={"fullText": "true"},
            timeout=10.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.warning(
            f"REST Countries API returned {e.response.status_code} for '{country_name}'"
        )
        return None
    except httpx.ConnectError:
        logger.warning("Cannot connect to REST Countries API — is the network available?")
        return None
    except httpx.TimeoutException:
        logger.warning(f"Timeout fetching country data for '{country_name}'")
        return None

    results = response.json()

    # API returns a list of matches; we take the first one
    if not results or not isinstance(results, list):
        logger.warning(f"Unexpected response format for '{country_name}'")
        return None

    return results[0]


def parse_country(raw: dict, country_name: str) -> dict:
    """
    Parse: Extract only the fields we need from the large API response.

    The API returns 20+ fields per country (population, currencies,
    languages, maps, etc). We only need region and subregion.
    """
    return {
        "country_name": country_name,
        "region": raw.get("region", ""),
        "subregion": raw.get("subregion", ""),
    }


def validate_country(parsed: dict) -> CountryInfo | None:
    """
    Validate: Run parsed data through our Pydantic model.

    Returns None if validation fails (e.g. empty region/subregion).
    """
    try:
        return CountryInfo(**parsed)
    except ValidationError as e:
        logger.warning(
            f"Country validation failed for '{parsed.get('country_name')}': {e}"
        )
        return None


def get_country_info(country_name: str) -> CountryInfo | None:
    """
    Get enriched country info, using cache if available.

    This is the per-country entry point: check cache -> fetch -> parse -> validate.
    """
    # Check cache first
    if country_name in _cache:
        logger.debug(f"Cache hit for '{country_name}'")
        return _cache[country_name]

    # Fetch from API
    raw = fetch_country(country_name)
    if raw is None:
        return None

    # Parse and validate
    parsed = parse_country(raw, country_name)
    validated = validate_country(parsed)

    # Store in cache (even if validated is None, we don't re-try failed countries)
    if validated:
        _cache[country_name] = validated

    return validated


def enrich_countries(country_names: list[str]) -> dict[str, CountryInfo]:
    """
    Main entry point: enrich a list of country names with region/subregion.

    Takes a list of country names (can have duplicates -- that's fine,
    the cache handles it). Returns a dict mapping country_name -> CountryInfo.
    """
    _cache.clear()  # Fresh data each run (idempotent)

    unique_countries = sorted(set(country_names))
    logger.info(
        f"Enriching {len(unique_countries)} unique countries "
        f"(from {len(country_names)} merchants)"
    )

    results: dict[str, CountryInfo] = {}
    failed = []

    for country in unique_countries:
        info = get_country_info(country)
        if info:
            results[country] = info
        else:
            failed.append(country)

    logger.info(
        f"Country enrichment complete: {len(results)} enriched, "
        f"{len(failed)} failed"
    )
    if failed:
        logger.warning(f"Failed countries: {failed}")

    return results
