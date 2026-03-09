"""
Client for the mock internal risk API: fetch -> parse -> validate.

This module calls our locally-running FastAPI mock server and
validates the responses using the same Pydantic models.

In production, this would call a real internal API endpoint.
"""

import logging

import httpx
from pydantic import ValidationError

from ingestion.validators import MerchantAPIResponse

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:8000"


def fetch_all_merchants(base_url: str = DEFAULT_BASE_URL) -> list[dict]:
    """
    Fetch: Call the /merchants endpoint to get all merchant risk data.

    httpx is an HTTP client library (like requests, but supports async too).
    We use it to make an HTTP GET request and get back JSON.
    """
    url = f"{base_url}/merchants"
    logger.info(f"Fetching all merchants from mock API: {url}")

    try:
        response = httpx.get(url, timeout=30.0)
        response.raise_for_status()  # Raises exception if status code is 4xx or 5xx
    except httpx.ConnectError:
        logger.error(
            f"Cannot connect to mock API at {base_url}. "
            "Is the server running? Start it with: "
            "uv run uvicorn ingestion.mock_api_server:app --port 8000"
        )
        raise
    except httpx.HTTPStatusError as e:
        logger.error(f"Mock API returned error: {e.response.status_code}")
        raise

    data = response.json()  # Parse JSON response into Python list of dicts
    logger.info(f"Fetched {len(data)} merchant records from mock API")
    return data


def validate_api_responses(raw_responses: list[dict]) -> list[MerchantAPIResponse]:
    """
    Validate: Run each API response through the Pydantic model.

    Same pattern as CSV validation -- valid records are kept,
    invalid records are logged and skipped.
    """
    valid_records = []
    invalid_count = 0

    for record in raw_responses:
        try:
            validated = MerchantAPIResponse(**record)
            valid_records.append(validated)
        except ValidationError as e:
            invalid_count += 1
            logger.warning(
                f"API record failed validation: {record.get('merchant_id', 'UNKNOWN')} - {e}"
            )

    logger.info(
        f"API validation complete: {len(valid_records)} valid, {invalid_count} invalid"
    )
    return valid_records


def ingest_mock_api(base_url: str = DEFAULT_BASE_URL) -> list[MerchantAPIResponse]:
    """
    Main entry point: fetch -> validate.

    Note: no separate "parse" step needed here because the API
    already returns JSON that maps directly to our Pydantic model.
    The HTTP client (httpx) handles JSON parsing via response.json().
    """
    raw_data = fetch_all_merchants(base_url)
    valid_records = validate_api_responses(raw_data)
    return valid_records
