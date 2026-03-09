"""
Mock API server: simulates an internal merchant risk API.

In production, this would be a real internal service. For the take-home,
we run this locally and our pipeline calls it via HTTP.

The server generates realistic data for all 50 merchants based on
their CSV data (monthly_volume, dispute_count, transaction_count).

Run with: uv run uvicorn ingestion.mock_api_server:app --port 8000
"""

import csv
import logging
import random
from pathlib import Path

from fastapi import FastAPI, HTTPException

from ingestion.validators import MerchantAPIResponse, TransactionSummary

logger = logging.getLogger(__name__)

app = FastAPI(title="Internal Merchant Risk API")

# Store generated data in memory so responses are consistent across requests
# (idempotent: same request always returns same data within a server session)
_merchant_data: dict[str, MerchantAPIResponse] = {}


def _assign_risk_flag(dispute_count: int, transaction_count: int) -> str:
    """
    Assign a risk flag based on dispute rate.

    This is a simple heuristic for the mock:
    - dispute_rate >= 0.15% -> high
    - dispute_rate >= 0.05% -> medium
    - otherwise -> low

    In production, this would come from a real risk model.
    """
    if transaction_count == 0:
        return "high"
    dispute_rate = dispute_count / transaction_count
    if dispute_rate >= 0.0015:
        return "high"
    elif dispute_rate >= 0.0005:
        return "medium"
    else:
        return "low"


def _generate_review_date(risk_flag: str) -> str | None:
    """
    Generate a plausible last review date.
    Higher-risk merchants get reviewed more recently.
    """
    if risk_flag == "high":
        return "2025-02-01"
    elif risk_flag == "medium":
        return "2025-01-15"
    else:
        return "2024-12-01"


def _load_merchant_data():
    """
    Read merchants.csv and generate API response data for each merchant.

    We use the CSV data to create realistic mock data:
    - last_30d_volume is based on monthly_volume (with slight variation)
    - last_30d_txn_count is based on transaction_count
    - avg_ticket_size = volume / txn_count
    - risk_flag is derived from dispute_rate
    """
    csv_path = Path("data/merchants.csv")
    if not csv_path.exists():
        return

    random.seed(42)  # Fixed seed for reproducibility (same data every run)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            merchant_id = row["merchant_id"].strip()
            monthly_volume = int(row["monthly_volume"])
            dispute_count = int(row["dispute_count"])
            transaction_count = int(row["transaction_count"])

            # Generate realistic 30-day metrics with slight random variation
            variation = random.uniform(0.85, 1.15)
            last_30d_volume = round(monthly_volume * variation, 2)
            last_30d_txn_count = max(1, int(transaction_count * variation))
            avg_ticket_size = round(last_30d_volume / last_30d_txn_count, 2)

            risk_flag = _assign_risk_flag(dispute_count, transaction_count)
            review_date = _generate_review_date(risk_flag)

            _merchant_data[merchant_id] = MerchantAPIResponse(
                merchant_id=merchant_id,
                internal_risk_flag=risk_flag,
                transaction_summary=TransactionSummary(
                    last_30d_volume=last_30d_volume,
                    last_30d_txn_count=last_30d_txn_count,
                    avg_ticket_size=avg_ticket_size,
                ),
                last_review_date=review_date,
            )


# Load data when the module is imported (server startup)
_load_merchant_data()
logger.info(f"Mock API loaded {len(_merchant_data)} merchants from CSV")


@app.get("/merchants/{merchant_id}", response_model=MerchantAPIResponse)
def get_merchant(merchant_id: str):
    """
    Get risk data for a single merchant by ID.

    Returns 404 if merchant not found.
    """
    if merchant_id not in _merchant_data:
        logger.warning(f"Merchant not found: {merchant_id}")
        raise HTTPException(status_code=404, detail=f"Merchant {merchant_id} not found")
    return _merchant_data[merchant_id]


@app.get("/merchants", response_model=list[MerchantAPIResponse])
def list_merchants():
    """
    Get risk data for all merchants.

    Returns a list of all merchant records.
    """
    return list(_merchant_data.values())
