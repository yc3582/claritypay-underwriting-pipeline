"""
CSV ingestion module: fetch -> parse -> validate for merchants.csv.

Follows the pattern required by the assignment:
1. Fetch: Read the CSV file from disk
2. Parse: Convert each row into a dictionary
3. Validate: Run each row through the Pydantic MerchantCSVRow model
   - Valid rows are returned
   - Invalid rows are logged and skipped
"""

import csv
import logging
from pathlib import Path

from ingestion.validators import MerchantCSVRow
from pydantic import ValidationError

logger = logging.getLogger(__name__)


def fetch_csv(file_path: Path) -> list[dict]:
    """
    Fetch: Read the CSV file and return rows as a list of dicts.

    csv.DictReader automatically uses the header row as keys,
    so each row becomes {"merchant_id": "M001", "name": "...", ...}.
    """
    logger.info(f"Fetching CSV from {file_path}")

    if not file_path.exists():
        logger.error(f"CSV file not found: {file_path}")
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    logger.info(f"Fetched {len(rows)} rows from CSV")
    return rows


def parse_row(raw_row: dict) -> dict:
    """
    Parse: Clean up a raw CSV row before validation.

    CSV files read everything as strings, so we need to:
    - Convert numeric fields to integers
    - Convert empty strings to None (for optional fields)
    """
    parsed = {}
    for key, value in raw_row.items():
        # Strip whitespace from keys and values
        key = key.strip()
        value = value.strip() if value else value

        # Convert empty strings to None (for optional fields like registration_number)
        if value == "":
            parsed[key] = None
        else:
            parsed[key] = value

    # Convert numeric fields from strings to integers
    for int_field in ("monthly_volume", "dispute_count", "transaction_count"):
        if parsed.get(int_field) is not None:
            try:
                parsed[int_field] = int(parsed[int_field])
            except (ValueError, TypeError):
                # Leave as-is; Pydantic will catch the type error during validation
                pass

    return parsed


def validate_rows(raw_rows: list[dict]) -> list[MerchantCSVRow]:
    """
    Validate: Run each parsed row through the Pydantic model.

    Returns only valid rows. Invalid rows are logged with details
    about what failed, so the risk team can investigate.
    """
    valid_merchants = []
    invalid_count = 0

    for i, raw_row in enumerate(raw_rows):
        parsed = parse_row(raw_row)
        try:
            merchant = MerchantCSVRow(**parsed)
            valid_merchants.append(merchant)
        except ValidationError as e:
            invalid_count += 1
            logger.warning(
                f"Row {i + 1} failed validation: {parsed.get('merchant_id', 'UNKNOWN')} - {e}"
            )

    logger.info(
        f"Validation complete: {len(valid_merchants)} valid, {invalid_count} invalid"
    )
    return valid_merchants


def ingest_csv(file_path: Path) -> list[MerchantCSVRow]:
    """
    Main entry point: fetch -> parse -> validate.

    This is what the pipeline orchestrator calls.
    Returns a list of validated MerchantCSVRow objects.
    """
    raw_rows = fetch_csv(file_path)
    valid_merchants = validate_rows(raw_rows)
    return valid_merchants
