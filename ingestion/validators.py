"""
Pydantic models for validating data from all sources.

Each model defines a schema (blueprint) that data must match.
If data doesn't match, Pydantic raises a ValidationError with
a clear message explaining what went wrong.

Models are organized by phase:
- Ingestion models (Phase 1): validate raw data from each source
- Collation models (Phase 2): validate the merged/joined output
"""

from pydantic import BaseModel, Field  # Field adds constraints beyond type checking
from typing import Literal, Optional


class MerchantCSVRow(BaseModel):
    """
    Schema for one row of merchants.csv.

    Each field maps to a CSV column. Pydantic will:
    - Check that required fields are present
    - Check that types are correct (e.g., monthly_volume is an int)
    - Check value constraints (e.g., monthly_volume >= 0)
    - Allow optional fields to be None (registration_number)
    """

    merchant_id: str = Field(
        ...,  # ... means "required"
        pattern=r"^M\d{3}$",  # Must match M followed by 3 digits
        description="Unique merchant identifier (e.g., M001)",
    )
    name: str = Field(
        ...,
        min_length=1,
        description="Merchant business name",
    )
    country: str = Field(
        ...,
        min_length=1,
        description="Country where the merchant is registered",
    )
    registration_number: Optional[str] = Field(
        default=None,
        description="Company registration number (UK merchants only)",
    )
    monthly_volume: int = Field(
        ...,
        ge=0,  # ge = greater than or equal to
        description="Monthly transaction volume in currency units",
    )
    dispute_count: int = Field(
        ...,
        ge=0,
        description="Number of disputes filed against this merchant",
    )
    transaction_count: int = Field(
        ...,
        ge=0,
        description="Total number of transactions",
    )


class TransactionSummary(BaseModel):
    """
    Nested object inside the API response.
    Contains recent transaction metrics for a merchant.
    """

    last_30d_volume: float = Field(
        ...,
        ge=0,
        description="Total transaction volume in last 30 days",
    )
    last_30d_txn_count: int = Field(
        ...,
        ge=0,
        description="Number of transactions in last 30 days",
    )
    avg_ticket_size: float = Field(
        ...,
        ge=0,
        description="Average transaction amount",
    )


class MerchantAPIResponse(BaseModel):
    """
    Schema for the mock API response, matching data/simulated_api_contract.json.

    Literal["low", "medium", "high"] restricts internal_risk_flag to only
    those three values -- same as "enum" in the JSON Schema contract.
    """

    merchant_id: str = Field(
        ...,
        pattern=r"^M\d{3}$",
        description="Must match merchant_id from merchants.csv",
    )
    internal_risk_flag: Literal["low", "medium", "high"] = Field(
        ...,
        description="Internal underwriting risk tier",
    )
    transaction_summary: TransactionSummary = Field(
        ...,
        description="Recent transaction metrics",
    )
    last_review_date: Optional[str] = Field(
        default=None,
        description="ISO date when merchant was last reviewed (optional)",
    )


class CountryInfo(BaseModel):
    """
    Schema for enriched country data from REST Countries API.

    We extract only region and subregion -- these are the fields
    useful for geographic risk grouping in underwriting.
    """

    country_name: str = Field(
        ...,
        min_length=1,
        description="Country name as it appears in merchants.csv",
    )
    region: str = Field(
        ...,
        min_length=1,
        description="Continent-level grouping (e.g. 'Europe', 'Americas')",
    )
    subregion: str = Field(
        ...,
        min_length=1,
        description="More specific area (e.g. 'Northern Europe', 'North America')",
    )


class PDFSummary(BaseModel):
    """
    Schema for text extracted from sample_merchant_summary.pdf.

    This PDF is for ONE sample merchant, not per-merchant.
    The raw text is included in the collated view / report context.
    Structured parsing is optional per assignment.
    """

    source_file: str = Field(
        ...,
        description="Path to the PDF file that was processed",
    )
    raw_text: str = Field(
        ...,
        min_length=1,
        description="Full extracted text from the PDF",
    )


class ScrapedSiteData(BaseModel):
    """
    Schema for data scraped from claritypay.com.

    This is company-level context (not per-merchant).
    Used as background context in the LLM report.
    """

    url: str = Field(
        ...,
        description="The URL that was scraped",
    )
    value_propositions: list[str] = Field(
        ...,
        description="Main value propositions / taglines from the site",
    )
    partners: list[str] = Field(
        ...,
        description="Partner company names found on the site",
    )
    stats: dict[str, str] = Field(
        ...,
        description="Public stats (e.g. {'merchants_served': '1900+'})",
    )


# --- Phase 2: Collation models ---


class CollatedMerchant(BaseModel):
    """
    One row of the collated dataset: a single merchant with fields
    merged from CSV + Mock API + REST Countries.

    This is the "questionnaire-style input for underwriting" that
    the assignment asks for. Each field answers an underwriting question:
    - Who is this merchant? (merchant_id, name)
    - Where are they? (country, region, subregion)
    - Are they UK-registered? (registration_number)
    - What's their volume? (monthly_volume, last_30d_volume, avg_ticket_size)
    - What's their dispute history? (dispute_count, transaction_count)
    - What does internal review say? (internal_risk_flag, last_review_date)

    API and country fields are Optional because those sources can fail.
    CSV fields are required (they're our base data).
    """

    # --- From CSV (required -- this is our base data) ---
    merchant_id: str = Field(
        ...,
        pattern=r"^M\d{3}$",
        description="Unique merchant identifier",
    )
    name: str = Field(..., min_length=1, description="Merchant business name")
    country: str = Field(..., min_length=1, description="Country of registration")
    registration_number: Optional[str] = Field(
        default=None,
        description="UK company registration number (None for non-UK)",
    )
    monthly_volume: int = Field(..., ge=0, description="Monthly transaction volume")
    dispute_count: int = Field(..., ge=0, description="Number of disputes")
    transaction_count: int = Field(..., ge=0, description="Total transactions")

    # --- From Mock API (optional -- API could be down) ---
    internal_risk_flag: Optional[Literal["low", "medium", "high"]] = Field(
        default=None,
        description="Internal underwriting risk tier from API",
    )
    last_30d_volume: Optional[float] = Field(
        default=None,
        ge=0,
        description="Transaction volume in last 30 days",
    )
    last_30d_txn_count: Optional[int] = Field(
        default=None,
        ge=0,
        description="Transaction count in last 30 days",
    )
    avg_ticket_size: Optional[float] = Field(
        default=None,
        ge=0,
        description="Average transaction amount",
    )
    last_review_date: Optional[str] = Field(
        default=None,
        description="ISO date of last internal review",
    )

    # --- From REST Countries (optional -- API could fail) ---
    region: Optional[str] = Field(
        default=None,
        description="Continent-level grouping (e.g. 'Europe')",
    )
    subregion: Optional[str] = Field(
        default=None,
        description="Sub-continental area (e.g. 'Northern Europe')",
    )


class CollatedDataset(BaseModel):
    """
    The full collated output: all merchants plus supplementary context.

    This is the single object passed to downstream phases:
    - Phase 3 (features): uses merchants list
    - Phase 6 (LLM report): uses merchants + pdf_summary + scrape_data
    """

    merchants: list[CollatedMerchant] = Field(
        ...,
        min_length=1,
        description="All merchants with merged data from CSV + API + Countries",
    )
    pdf_summary: Optional[PDFSummary] = Field(
        default=None,
        description="Supplementary: extracted text from sample PDF (M001 only)",
    )
    scrape_data: Optional[ScrapedSiteData] = Field(
        default=None,
        description="Supplementary: company-level context from claritypay.com",
    )
