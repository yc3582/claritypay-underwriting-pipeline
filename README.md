# ClarityPay Merchant Underwriting Pipeline

A merchant underwriting pipeline for ClarityPay (BNPL). Ingests data from 5 sources, engineers risk features, trains a dispute-risk model, aggregates portfolio-level exposure, and generates an LLM-powered underwriting report.

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Anthropic API key (for the LLM report generation step)

### Setup

```bash
# Install dependencies
uv sync

# Set up your Anthropic API key
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

### Run the Pipeline

The pipeline requires two terminals:

**Terminal 1** — Start the mock API server:
```bash
uv run uvicorn ingestion.mock_api_server:app --port 8000
```

**Terminal 2** — Run the pipeline:
```bash
export $(cat .env | xargs)
uv run python run_pipeline.py
```

The pipeline will:
1. Ingest data from CSV, mock API, REST Countries API, PDF, and claritypay.com
2. Collate into a single structured dataset (one row per merchant)
3. Engineer 7 features and compute binary risk labels
4. Train a decision tree model and evaluate it
5. Aggregate portfolio-level risk (expected loss)
6. Call Claude API to generate the underwriting report

Output is saved to `output/risk_report.md`.

### Run Tests

```bash
uv run pytest tests/ -v
```

42 unit tests covering validation schemas, CSV ingestion path, and feature engineering logic.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for LLM report generation |

## Project Structure

```
run_pipeline.py          # Main entry point — runs all phases end-to-end
ingestion/
  validators.py          # Pydantic schemas for all data sources + collated output
  csv_ingest.py          # CSV ingestion (fetch -> parse -> validate)
  mock_api_server.py     # FastAPI mock API server (simulates internal risk API)
  mock_api_client.py     # HTTP client for mock API
  countries_client.py    # REST Countries API client with dict cache
  pdf_ingest.py          # Async PDF text extraction (pdfplumber)
  scraper.py             # claritypay.com scraper (BeautifulSoup)
collation/
  collate.py             # Merge all sources into CollatedDataset
features/
  feature_engineering.py # Target computation, volume banding, feature DataFrame
model/
  train.py               # Decision tree training, evaluation, prediction
  portfolio.py           # Portfolio-level risk aggregation (expected loss)
reporting/
  generate_report.py     # LLM report generation via Anthropic Claude API
tests/
  test_validators.py     # Pydantic schema validation tests (12 tests)
  test_csv_ingest.py     # CSV ingestion path tests (8 tests)
  test_features.py       # Feature engineering tests (22 tests)
data/
  merchants.csv          # 50 merchants with volume, disputes, country
  sample_merchant_summary.pdf  # Sample merchant document (M001)
  simulated_api_contract.json  # API contract for mock server
output/
  risk_report.md         # Generated underwriting report (LLM output)
```

## Data Sources

| Source | Type | What it provides |
|--------|------|-----------------|
| `merchants.csv` | CSV file | 50 merchants: ID, name, country, volume, disputes, transactions |
| Mock API | FastAPI server | Internal risk flags (low/medium/high), 30-day transaction summary |
| REST Countries | Public API | Region and subregion for geographic risk grouping |
| Sample PDF | PDF file | Merchant summary document for M001 (text context for report) |
| claritypay.com | Web scrape | Company value propositions, partner names, public stats |

## Model Summary

- **Algorithm**: Decision Tree (max_depth=3, class_weight=balanced)
- **Features**: 7 (volume_band, is_uk, has_registration, risk_flag_encoded, avg_ticket_size, volume_trend, subregion_encoded)
- **Target**: Binary — high dispute risk (dispute_rate >= 0.1%)
- **Split**: 80/20 stratified
- **Results**: 90% accuracy, 67% high-risk recall, 100% precision
- **Portfolio**: 19/50 merchants flagged high-risk (38%), $1.03M expected loss exposure of $4.38M total (23.5%)
