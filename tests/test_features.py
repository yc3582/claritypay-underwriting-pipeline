"""
Tests for feature engineering logic.

Covers: target computation, volume banding, feature DataFrame construction.
These are critical for model correctness — wrong features = wrong predictions.
"""

import pytest

from features.feature_engineering import (
    compute_target,
    compute_volume_band,
    build_feature_dataframe,
    HIGH_RISK_THRESHOLD,
    RISK_FLAG_MAP,
)
from ingestion.validators import CollatedMerchant


def make_merchant(**overrides) -> CollatedMerchant:
    """Helper: create a CollatedMerchant with sensible defaults."""
    defaults = {
        "merchant_id": "M001",
        "name": "Test",
        "country": "United Kingdom",
        "monthly_volume": 50000,
        "dispute_count": 0,
        "transaction_count": 1000,
    }
    defaults.update(overrides)
    return CollatedMerchant(**defaults)


class TestComputeTarget:
    """Test binary target label computation."""

    def test_high_risk_above_threshold(self):
        """dispute_rate >= 0.001 should be labeled 1."""
        # 1/1000 = 0.001 = exactly at threshold
        m = make_merchant(dispute_count=1, transaction_count=1000)
        targets = compute_target([m])
        assert targets == [1]

    def test_low_risk_below_threshold(self):
        """dispute_rate < 0.001 should be labeled 0."""
        # 0/1000 = 0.0
        m = make_merchant(dispute_count=0, transaction_count=1000)
        targets = compute_target([m])
        assert targets == [0]

    def test_zero_transactions(self):
        """Merchant with 0 transactions gets rate=0 (low risk)."""
        m = make_merchant(dispute_count=0, transaction_count=0)
        targets = compute_target([m])
        assert targets == [0]

    def test_multiple_merchants(self):
        merchants = [
            make_merchant(merchant_id="M001", dispute_count=5, transaction_count=1000),  # 0.5% = high
            make_merchant(merchant_id="M002", dispute_count=0, transaction_count=1000),  # 0% = low
            make_merchant(merchant_id="M003", dispute_count=1, transaction_count=2000),  # 0.05% = low
        ]
        targets = compute_target(merchants)
        assert targets == [1, 0, 0]


class TestComputeVolumeBand:
    """Test volume banding logic."""

    def test_low_band(self):
        assert compute_volume_band(10_000) == 0
        assert compute_volume_band(50_999) == 0

    def test_medium_band(self):
        assert compute_volume_band(51_000) == 1
        assert compute_volume_band(95_000) == 1

    def test_high_band(self):
        assert compute_volume_band(95_001) == 2
        assert compute_volume_band(200_000) == 2

    def test_boundary_low_medium(self):
        """51,000 is the first medium value."""
        assert compute_volume_band(50_999) == 0
        assert compute_volume_band(51_000) == 1

    def test_boundary_medium_high(self):
        """95,000 is the last medium value."""
        assert compute_volume_band(95_000) == 1
        assert compute_volume_band(95_001) == 2

    def test_zero_volume(self):
        assert compute_volume_band(0) == 0


class TestBuildFeatureDataFrame:
    """Test feature DataFrame construction."""

    def test_returns_dataframe_and_columns(self):
        merchants = [make_merchant()]
        df, cols = build_feature_dataframe(merchants)
        assert len(df) == 1
        assert len(cols) == 7

    def test_feature_columns_present(self):
        merchants = [make_merchant()]
        df, cols = build_feature_dataframe(merchants)
        expected = [
            "volume_band", "is_uk", "has_registration",
            "risk_flag_encoded", "avg_ticket_size",
            "volume_trend", "subregion_encoded",
        ]
        assert cols == expected

    def test_is_uk_flag(self):
        uk = make_merchant(merchant_id="M001", country="United Kingdom")
        de = make_merchant(merchant_id="M002", country="Germany")
        df, _ = build_feature_dataframe([uk, de])
        assert df.iloc[0]["is_uk"] == 1
        assert df.iloc[1]["is_uk"] == 0

    def test_risk_flag_encoding(self):
        low = make_merchant(merchant_id="M001", internal_risk_flag="low")
        med = make_merchant(merchant_id="M002", internal_risk_flag="medium")
        high = make_merchant(merchant_id="M003", internal_risk_flag="high")
        df, _ = build_feature_dataframe([low, med, high])
        assert df.iloc[0]["risk_flag_encoded"] == 0
        assert df.iloc[1]["risk_flag_encoded"] == 1
        assert df.iloc[2]["risk_flag_encoded"] == 2

    def test_missing_risk_flag_defaults_to_negative_one(self):
        m = make_merchant(internal_risk_flag=None)
        df, _ = build_feature_dataframe([m])
        assert df.iloc[0]["risk_flag_encoded"] == -1

    def test_missing_avg_ticket_defaults_to_zero(self):
        m = make_merchant(avg_ticket_size=None)
        df, _ = build_feature_dataframe([m])
        assert df.iloc[0]["avg_ticket_size"] == 0.0

    def test_volume_trend_calculation(self):
        m = make_merchant(monthly_volume=100_000, last_30d_volume=120_000.0)
        df, _ = build_feature_dataframe([m])
        assert df.iloc[0]["volume_trend"] == pytest.approx(1.2)

    def test_volume_trend_missing_defaults_to_one(self):
        m = make_merchant(last_30d_volume=None)
        df, _ = build_feature_dataframe([m])
        assert df.iloc[0]["volume_trend"] == 1.0

    def test_has_registration(self):
        with_reg = make_merchant(merchant_id="M001", registration_number="12345")
        without_reg = make_merchant(merchant_id="M002", registration_number=None)
        df, _ = build_feature_dataframe([with_reg, without_reg])
        assert df.iloc[0]["has_registration"] == 1
        assert df.iloc[1]["has_registration"] == 0
