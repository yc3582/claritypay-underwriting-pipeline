"""
Tests for CSV ingestion path.

Covers: fetch, parse, validate flow with real data file.
Assignment requirement: "at least a few unit tests (e.g. ... one ingestion path)."
"""

import pytest
from pathlib import Path

from ingestion.csv_ingest import ingest_csv, parse_row, validate_rows


class TestCSVIngestion:
    """Test the CSV ingestion pipeline."""

    def test_ingest_real_csv(self):
        """Full ingestion of the real merchants.csv file."""
        rows = ingest_csv(Path("data/merchants.csv"))
        assert len(rows) == 50
        # Check first merchant
        assert rows[0].merchant_id == "M001"
        assert rows[0].name == "GreenLeaf Retail Ltd"

    def test_all_merchant_ids_valid(self):
        """Every merchant_id follows the M### pattern."""
        rows = ingest_csv(Path("data/merchants.csv"))
        for row in rows:
            assert row.merchant_id.startswith("M")
            assert len(row.merchant_id) == 4

    def test_no_negative_values(self):
        """No merchant has negative volume, disputes, or transactions."""
        rows = ingest_csv(Path("data/merchants.csv"))
        for row in rows:
            assert row.monthly_volume >= 0
            assert row.dispute_count >= 0
            assert row.transaction_count >= 0

    def test_parse_row_converts_types(self):
        """parse_row converts string numbers to ints, empty strings to None."""
        raw = {
            "merchant_id": "M001",
            "name": "Test Merchant",
            "country": "United Kingdom",
            "registration_number": "12345678",
            "monthly_volume": "50000",
            "dispute_count": "3",
            "transaction_count": "1000",
        }
        parsed = parse_row(raw)
        assert parsed["monthly_volume"] == 50000  # String "50000" -> int
        assert parsed["dispute_count"] == 3

    def test_parse_row_empty_registration_becomes_none(self):
        """Empty registration_number becomes None."""
        raw = {
            "merchant_id": "M002",
            "name": "Foreign Merchant",
            "country": "Germany",
            "registration_number": "",
            "monthly_volume": "30000",
            "dispute_count": "1",
            "transaction_count": "500",
        }
        parsed = parse_row(raw)
        assert parsed["registration_number"] is None

    def test_parse_row_non_numeric_volume_left_as_string(self):
        """Non-numeric volume is left as-is (Pydantic will catch it)."""
        raw = {
            "merchant_id": "M001",
            "name": "Test",
            "country": "UK",
            "registration_number": "",
            "monthly_volume": "not_a_number",
            "dispute_count": "0",
            "transaction_count": "100",
        }
        parsed = parse_row(raw)
        assert parsed["monthly_volume"] == "not_a_number"

    def test_validate_rows_filters_invalid(self):
        """validate_rows returns only valid rows, logs invalid ones."""
        raw_rows = [
            {
                "merchant_id": "M001",
                "name": "Good",
                "country": "UK",
                "registration_number": "",
                "monthly_volume": "1000",
                "dispute_count": "0",
                "transaction_count": "100",
            },
            {
                "merchant_id": "INVALID",
                "name": "Bad",
                "country": "UK",
                "registration_number": "",
                "monthly_volume": "abc",
                "dispute_count": "0",
                "transaction_count": "100",
            },
        ]
        valid = validate_rows(raw_rows)
        assert len(valid) == 1
        assert valid[0].merchant_id == "M001"

    def test_file_not_found(self):
        """Missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            ingest_csv(Path("data/nonexistent.csv"))
