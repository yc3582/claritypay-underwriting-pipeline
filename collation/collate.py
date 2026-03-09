"""
Collation: merge data from all 5 ingestion sources into one structured dataset.

Per-merchant data (CSV + API + Countries) is joined into one row per merchant.
Supplementary context (PDF + scrape) is attached separately since it's not
per-merchant data.

Join strategy:
- CSV ↔ API: by merchant_id (dict lookup)
- CSV ↔ Countries: by country name (dict lookup)
- If a join fails, Optional fields stay None (graceful degradation).
"""

import logging

from ingestion.validators import (
    CollatedDataset,
    CollatedMerchant,
    CountryInfo,
    MerchantAPIResponse,
    MerchantCSVRow,
    PDFSummary,
    ScrapedSiteData,
)

logger = logging.getLogger(__name__)


def collate_merchant(
    csv_row: MerchantCSVRow,
    api_dict: dict[str, MerchantAPIResponse],
    country_dict: dict[str, CountryInfo],
) -> CollatedMerchant:
    """
    Merge one merchant's data from all per-merchant sources.

    Starts with CSV data (the base), then enriches with API and country data
    via dict lookups. If a lookup fails, those fields stay None.
    """
    # Start with CSV fields (always present)
    fields: dict = {
        "merchant_id": csv_row.merchant_id,
        "name": csv_row.name,
        "country": csv_row.country,
        "registration_number": csv_row.registration_number,
        "monthly_volume": csv_row.monthly_volume,
        "dispute_count": csv_row.dispute_count,
        "transaction_count": csv_row.transaction_count,
    }

    # Enrich with API data (join by merchant_id)
    api_data = api_dict.get(csv_row.merchant_id)
    if api_data:
        fields["internal_risk_flag"] = api_data.internal_risk_flag
        fields["last_30d_volume"] = api_data.transaction_summary.last_30d_volume
        fields["last_30d_txn_count"] = api_data.transaction_summary.last_30d_txn_count
        fields["avg_ticket_size"] = api_data.transaction_summary.avg_ticket_size
        fields["last_review_date"] = api_data.last_review_date
    else:
        logger.warning(f"No API data for {csv_row.merchant_id} -- fields will be None")

    # Enrich with country data (join by country name)
    country_data = country_dict.get(csv_row.country)
    if country_data:
        fields["region"] = country_data.region
        fields["subregion"] = country_data.subregion
    else:
        logger.warning(
            f"No country data for {csv_row.country} "
            f"(merchant {csv_row.merchant_id}) -- fields will be None"
        )

    return CollatedMerchant(**fields)


def collate_dataset(
    csv_rows: list[MerchantCSVRow],
    api_responses: list[MerchantAPIResponse],
    country_data: dict[str, CountryInfo],
    pdf_summary: PDFSummary | None = None,
    scrape_data: ScrapedSiteData | None = None,
) -> CollatedDataset:
    """
    Main entry point: merge all sources into the collated dataset.

    1. Build lookup dicts from API responses and country data
    2. For each CSV row, merge in API + country data
    3. Attach PDF and scrape as supplementary context
    """
    logger.info(
        f"Collating {len(csv_rows)} merchants with "
        f"{len(api_responses)} API responses and "
        f"{len(country_data)} country records"
    )

    # Build API lookup dict: merchant_id -> MerchantAPIResponse
    api_dict: dict[str, MerchantAPIResponse] = {
        resp.merchant_id: resp for resp in api_responses
    }

    # Merge each merchant
    merchants = []
    for csv_row in csv_rows:
        merchant = collate_merchant(csv_row, api_dict, country_data)
        merchants.append(merchant)

    # Count how many had complete data
    complete = sum(
        1 for m in merchants
        if m.internal_risk_flag is not None and m.region is not None
    )
    logger.info(
        f"Collation complete: {len(merchants)} merchants "
        f"({complete} with full data from all sources)"
    )

    return CollatedDataset(
        merchants=merchants,
        pdf_summary=pdf_summary,
        scrape_data=scrape_data,
    )
