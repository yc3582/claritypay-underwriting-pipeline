"""
Feature engineering: derive model-ready features from collated merchant data.

Transforms raw collated fields into numeric features that a ML model can
learn from. Each feature is chosen because it answers an underwriting question.

Key assumptions (documented per assignment requirement):
- dispute_rate is used ONLY to define the target label, NOT as a feature
  (using it as a feature would be data leakage -- circular logic)
- volume_band thresholds are based on the data distribution (terciles)
- risk_flag has a natural order: low=0 < medium=1 < high=2
- subregion is label-encoded (decision trees handle this fine)
- Missing Optional fields (API/country) default to safe values (0 or -1)
"""

import logging

import pandas as pd

from ingestion.validators import CollatedMerchant

logger = logging.getLogger(__name__)

# Threshold for binary target: dispute_rate >= 0.1% = high risk
# Gives 16 high / 34 low out of 50 merchants (reasonable split)
HIGH_RISK_THRESHOLD = 0.001

# Risk flag ordinal encoding (natural order)
RISK_FLAG_MAP = {"low": 0, "medium": 1, "high": 2}


def compute_target(merchants: list[CollatedMerchant]) -> list[int]:
    """
    Compute the binary target variable: is this merchant high dispute risk?

    dispute_rate = dispute_count / transaction_count
    high_risk = 1 if dispute_rate >= HIGH_RISK_THRESHOLD else 0

    Merchants with 0 transactions get dispute_rate = 0 (no evidence of risk).
    """
    targets = []
    for m in merchants:
        if m.transaction_count > 0:
            dispute_rate = m.dispute_count / m.transaction_count
        else:
            dispute_rate = 0.0
        targets.append(1 if dispute_rate >= HIGH_RISK_THRESHOLD else 0)

    high_count = sum(targets)
    logger.info(
        f"Target distribution: {high_count} high risk, "
        f"{len(targets) - high_count} low risk "
        f"(threshold: {HIGH_RISK_THRESHOLD:.4f})"
    )
    return targets


def compute_volume_band(monthly_volume: int) -> int:
    """
    Categorize monthly volume into bands: 0=low, 1=medium, 2=high.

    Thresholds based on data distribution (roughly terciles):
    - Low: < 51,000     (~16 merchants)
    - Medium: 51,000 - 95,000  (~18 merchants)
    - High: > 95,000    (~16 merchants)

    Larger volume = more financial exposure per merchant.
    """
    if monthly_volume < 51_000:
        return 0
    elif monthly_volume <= 95_000:
        return 1
    else:
        return 2


def build_feature_dataframe(merchants: list[CollatedMerchant]) -> tuple[pd.DataFrame, list[str]]:
    """
    Transform collated merchants into a feature DataFrame for the model.

    Each row = one merchant. Each column = one numeric feature.
    Features are chosen to answer underwriting risk questions:

    1. volume_band: How big is this merchant? (exposure level)
    2. is_uk: Are they in a well-regulated market?
    3. has_registration: Are they a formally registered company?
    4. risk_flag_encoded: What does internal review say?
    5. avg_ticket_size: How much per transaction? (per-dispute loss)
    6. volume_trend: Is their business growing or shrinking?
    7. subregion_encoded: Where are they geographically?
    """
    rows = []
    for m in merchants:
        # Volume band (from CSV monthly_volume)
        volume_band = compute_volume_band(m.monthly_volume)

        # Is UK (from CSV country)
        is_uk = 1 if m.country == "United Kingdom" else 0

        # Has registration number (from CSV)
        has_registration = 1 if m.registration_number is not None else 0

        # Risk flag encoded (from API -- default to -1 if missing)
        risk_flag_encoded = RISK_FLAG_MAP.get(m.internal_risk_flag, -1)

        # Average ticket size (from API -- default to 0 if missing)
        avg_ticket_size = m.avg_ticket_size if m.avg_ticket_size is not None else 0.0

        # Volume trend: ratio of last_30d_volume to monthly_volume
        # > 1.0 means growing, < 1.0 means shrinking
        # Default to 1.0 (neutral) if API data missing or monthly_volume is 0
        if m.last_30d_volume is not None and m.monthly_volume > 0:
            volume_trend = m.last_30d_volume / m.monthly_volume
        else:
            volume_trend = 1.0

        # Subregion encoded (from Countries API -- label encoding)
        # Will be converted to integer codes below
        subregion = m.subregion if m.subregion is not None else "Unknown"

        rows.append({
            "merchant_id": m.merchant_id,
            "volume_band": volume_band,
            "is_uk": is_uk,
            "has_registration": has_registration,
            "risk_flag_encoded": risk_flag_encoded,
            "avg_ticket_size": avg_ticket_size,
            "volume_trend": volume_trend,
            "subregion": subregion,
        })

    df = pd.DataFrame(rows)

    # Label-encode subregion: convert string categories to integer codes
    # Decision trees handle this fine (they split on thresholds)
    df["subregion_encoded"] = df["subregion"].astype("category").cat.codes

    # Drop the raw string column (model needs numbers only)
    # Keep merchant_id for reference but it's not a feature
    feature_columns = [
        "volume_band",
        "is_uk",
        "has_registration",
        "risk_flag_encoded",
        "avg_ticket_size",
        "volume_trend",
        "subregion_encoded",
    ]

    logger.info(
        f"Built feature DataFrame: {len(df)} rows, "
        f"{len(feature_columns)} features: {feature_columns}"
    )

    return df, feature_columns
