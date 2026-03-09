"""
Portfolio-level risk aggregation.

Zooms out from individual merchant predictions to portfolio-wide metrics.
Answers: "How much total risk does our merchant portfolio carry?"

Takes model predictions (from train.py) + collated merchant data and produces:
1. Expected high-risk count (how many merchants flagged)
2. Simple expected loss (volume-weighted risk across portfolio)
3. Risk distribution breakdown (for the risk team's report)

The expected loss calculation is simplified:
  expected_loss = sum(merchant_volume * prob_high_risk) for all merchants
This represents total monthly volume "at risk" of dispute issues.
In production, you'd multiply by an assumed loss-given-dispute rate.
"""

import logging

import numpy as np

from ingestion.validators import CollatedMerchant

logger = logging.getLogger(__name__)


def aggregate_portfolio(
    merchants: list[CollatedMerchant],
    predictions: np.ndarray,
    probabilities: np.ndarray,
) -> dict:
    """
    Compute portfolio-level risk metrics from model outputs.

    Args:
        merchants: All 50 collated merchants (need monthly_volume)
        predictions: Hard labels (0/1) from model.predict() for each merchant
        probabilities: Probability arrays from model.predict_proba() —
                       each row is [prob_low_risk, prob_high_risk]

    Returns:
        Dict with portfolio metrics for the LLM report.
    """
    n_total = len(merchants)
    n_high_risk = int(predictions.sum())
    n_low_risk = n_total - n_high_risk

    # --- Simple expected loss ---
    # For each merchant: monthly_volume * probability of being high risk
    # This gives "volume-weighted risk exposure"
    total_volume = 0
    expected_loss = 0.0
    for i, merchant in enumerate(merchants):
        prob_high = float(probabilities[i][1])  # Column 1 = prob of high risk
        total_volume += merchant.monthly_volume
        expected_loss += merchant.monthly_volume * prob_high

    # --- Risk distribution by predicted label ---
    high_risk_merchants = []
    low_risk_merchants = []
    for i, merchant in enumerate(merchants):
        entry = {
            "merchant_id": merchant.merchant_id,
            "name": merchant.name,
            "monthly_volume": merchant.monthly_volume,
            "prob_high_risk": round(float(probabilities[i][1]), 3),
        }
        if predictions[i] == 1:
            high_risk_merchants.append(entry)
        else:
            low_risk_merchants.append(entry)

    # Sort high-risk by probability (most risky first)
    high_risk_merchants.sort(key=lambda x: -x["prob_high_risk"])

    portfolio = {
        "total_merchants": n_total,
        "high_risk_count": n_high_risk,
        "low_risk_count": n_low_risk,
        "high_risk_pct": round(n_high_risk / n_total * 100, 1),
        "total_monthly_volume": total_volume,
        "expected_loss_volume": round(expected_loss, 2),
        "expected_loss_pct": round(expected_loss / total_volume * 100, 1) if total_volume > 0 else 0,
        "high_risk_merchants": high_risk_merchants,
        "low_risk_merchants": low_risk_merchants,
    }

    logger.info(
        f"Portfolio summary: {n_high_risk}/{n_total} high risk ({portfolio['high_risk_pct']}%), "
        f"expected loss volume: {expected_loss:,.0f} of {total_volume:,.0f} total "
        f"({portfolio['expected_loss_pct']}%)"
    )

    return portfolio
