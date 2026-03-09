"""
Tests for Pydantic validation models.

Covers: valid data passes, invalid data rejected with clear errors.
Assignment requirement: "Schema validation" and "at least a few unit tests."
"""

import pytest
from pydantic import ValidationError

from ingestion.validators import (
    MerchantCSVRow,
    MerchantAPIResponse,
    TransactionSummary,
    CountryInfo,
    CollatedMerchant,
)


# --- MerchantCSVRow ---


class TestMerchantCSVRow:
    """Test CSV row validation."""

    def test_valid_row(self):
        row = MerchantCSVRow(
            merchant_id="M001",
            name="Test Merchant",
            country="United Kingdom",
            registration_number="12345678",
            monthly_volume=50000,
            dispute_count=3,
            transaction_count=1000,
        )
        assert row.merchant_id == "M001"
        assert row.monthly_volume == 50000

    def test_valid_row_no_registration(self):
        """Non-UK merchants have no registration number."""
        row = MerchantCSVRow(
            merchant_id="M002",
            name="Foreign Merchant",
            country="Germany",
            registration_number=None,
            monthly_volume=30000,
            dispute_count=1,
            transaction_count=500,
        )
        assert row.registration_number is None

    def test_invalid_merchant_id_format(self):
        """merchant_id must match M followed by 3 digits."""
        with pytest.raises(ValidationError) as exc_info:
            MerchantCSVRow(
                merchant_id="INVALID",
                name="Test",
                country="UK",
                monthly_volume=1000,
                dispute_count=0,
                transaction_count=100,
            )
        assert "merchant_id" in str(exc_info.value)

    def test_invalid_merchant_id_too_many_digits(self):
        with pytest.raises(ValidationError):
            MerchantCSVRow(
                merchant_id="M1234",
                name="Test",
                country="UK",
                monthly_volume=1000,
                dispute_count=0,
                transaction_count=100,
            )

    def test_negative_volume_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            MerchantCSVRow(
                merchant_id="M001",
                name="Test",
                country="UK",
                monthly_volume=-1,
                dispute_count=0,
                transaction_count=100,
            )
        assert "monthly_volume" in str(exc_info.value)

    def test_negative_dispute_count_rejected(self):
        with pytest.raises(ValidationError):
            MerchantCSVRow(
                merchant_id="M001",
                name="Test",
                country="UK",
                monthly_volume=1000,
                dispute_count=-5,
                transaction_count=100,
            )

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            MerchantCSVRow(
                merchant_id="M001",
                name="",
                country="UK",
                monthly_volume=1000,
                dispute_count=0,
                transaction_count=100,
            )

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            MerchantCSVRow(
                merchant_id="M001",
                name="Test",
                # country is missing
                monthly_volume=1000,
                dispute_count=0,
                transaction_count=100,
            )


# --- MerchantAPIResponse ---


class TestMerchantAPIResponse:
    """Test API response validation."""

    def test_valid_response(self):
        resp = MerchantAPIResponse(
            merchant_id="M001",
            internal_risk_flag="medium",
            transaction_summary=TransactionSummary(
                last_30d_volume=45000.0,
                last_30d_txn_count=800,
                avg_ticket_size=56.25,
            ),
            last_review_date="2025-01-15",
        )
        assert resp.internal_risk_flag == "medium"
        assert resp.transaction_summary.avg_ticket_size == 56.25

    def test_invalid_risk_flag(self):
        """risk_flag must be one of low/medium/high."""
        with pytest.raises(ValidationError) as exc_info:
            MerchantAPIResponse(
                merchant_id="M001",
                internal_risk_flag="critical",  # not in enum
                transaction_summary=TransactionSummary(
                    last_30d_volume=1000.0,
                    last_30d_txn_count=10,
                    avg_ticket_size=100.0,
                ),
            )
        assert "internal_risk_flag" in str(exc_info.value)

    def test_negative_transaction_volume(self):
        with pytest.raises(ValidationError):
            MerchantAPIResponse(
                merchant_id="M001",
                internal_risk_flag="low",
                transaction_summary=TransactionSummary(
                    last_30d_volume=-500.0,
                    last_30d_txn_count=10,
                    avg_ticket_size=100.0,
                ),
            )


# --- CountryInfo ---


class TestCountryInfo:
    """Test country enrichment validation."""

    def test_valid_country(self):
        info = CountryInfo(
            country_name="United Kingdom",
            region="Europe",
            subregion="Northern Europe",
        )
        assert info.region == "Europe"

    def test_empty_region_rejected(self):
        with pytest.raises(ValidationError):
            CountryInfo(
                country_name="Test",
                region="",
                subregion="Test",
            )


# --- CollatedMerchant ---


class TestCollatedMerchant:
    """Test collated merchant validation (merged data)."""

    def test_valid_full_data(self):
        """All sources present."""
        m = CollatedMerchant(
            merchant_id="M001",
            name="Test",
            country="UK",
            monthly_volume=50000,
            dispute_count=3,
            transaction_count=1000,
            internal_risk_flag="medium",
            last_30d_volume=45000.0,
            avg_ticket_size=50.0,
            region="Europe",
            subregion="Northern Europe",
        )
        assert m.internal_risk_flag == "medium"
        assert m.region == "Europe"

    def test_valid_csv_only(self):
        """API and country fields can be None (graceful degradation)."""
        m = CollatedMerchant(
            merchant_id="M001",
            name="Test",
            country="UK",
            monthly_volume=50000,
            dispute_count=3,
            transaction_count=1000,
        )
        assert m.internal_risk_flag is None
        assert m.region is None
        assert m.avg_ticket_size is None
