"""
Main pipeline entry point: run all phases end-to-end.

Usage:
    1. Start the mock API server in a separate terminal:
       uv run uvicorn ingestion.mock_api_server:app --port 8000

    2. Export your Anthropic API key:
       export $(cat .env | xargs)

    3. Run the pipeline:
       uv run python run_pipeline.py

The pipeline runs phases sequentially:
    Phase 1: Ingest all 5 data sources (CSV, mock API, REST Countries, PDF, scrape)
    Phase 2: Collate into single structured dataset
    Phase 3: Engineer features + compute target labels
    Phase 4: Train risk model + evaluate
    Phase 5: Aggregate portfolio-level risk
    Phase 6: Generate LLM underwriting report
"""

import asyncio
import logging
from pathlib import Path

# --- Phase 1: Ingestion ---
from ingestion.csv_ingest import ingest_csv
from ingestion.mock_api_client import ingest_mock_api
from ingestion.countries_client import enrich_countries
from ingestion.pdf_ingest import ingest_pdf
from ingestion.scraper import ingest_scrape

# --- Phase 2: Collation ---
from collation.collate import collate_dataset

# --- Phase 3: Feature Engineering ---
from features.feature_engineering import compute_target, build_feature_dataframe

# --- Phase 4: Risk Model ---
from model.train import split_data, train_model, evaluate_model, predict_all

# --- Phase 5: Portfolio Aggregation ---
from model.portfolio import aggregate_portfolio

# --- Phase 6: LLM Report ---
from reporting.generate_report import generate_report, save_report


def setup_logging():
    """Configure logging for the pipeline run."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main():
    setup_logging()
    logger = logging.getLogger("pipeline")

    # ── Phase 1: Ingest all data sources ──
    logger.info("Phase 1: Ingesting data sources...")

    # 1a. CSV
    csv_rows = ingest_csv(Path("data/merchants.csv"))
    logger.info(f"  CSV: {len(csv_rows)} merchants")

    # 1b. Mock API (server must be running on port 8000)
    api_responses = ingest_mock_api()
    logger.info(f"  Mock API: {len(api_responses)} responses")

    # 1c. REST Countries
    unique_countries = list({row.country for row in csv_rows})
    country_data = enrich_countries(unique_countries)
    logger.info(f"  Countries: {len(country_data)} enriched")

    # 1d. PDF (async)
    pdf_summary = asyncio.run(ingest_pdf())
    logger.info(f"  PDF: {'extracted' if pdf_summary else 'failed'}")

    # 1e. Scrape
    scrape_data = ingest_scrape()
    logger.info(f"  Scrape: {'extracted' if scrape_data else 'failed'}")

    # ── Phase 2: Collate ──
    logger.info("Phase 2: Collating data...")
    dataset = collate_dataset(
        csv_rows=csv_rows,
        api_responses=api_responses,
        country_data=country_data,
        pdf_summary=pdf_summary,
        scrape_data=scrape_data,
    )
    logger.info(f"  Collated: {len(dataset.merchants)} merchants")

    # ── Phase 3: Feature Engineering ──
    logger.info("Phase 3: Engineering features...")
    targets = compute_target(dataset.merchants)
    df, feature_columns = build_feature_dataframe(dataset.merchants)
    X = df[feature_columns]
    logger.info(f"  Features: {len(feature_columns)} columns, target distribution: {sum(targets)} high / {len(targets) - sum(targets)} low")

    # ── Phase 4: Train & Evaluate Model ──
    logger.info("Phase 4: Training risk model...")
    X_train, X_test, y_train, y_test = split_data(X, targets)
    model = train_model(X_train, y_train)
    metrics = evaluate_model(model, X_test, y_test)
    logger.info(f"  Accuracy: {metrics['accuracy']:.0%}, High-risk recall: {metrics['high_risk_recall']:.0%}")

    # Full-dataset predictions for portfolio + report
    predictions, probabilities = predict_all(model, X)

    # Extract feature importances for the report
    feature_importances = list(zip(feature_columns, model.feature_importances_))

    # ── Phase 5: Portfolio Aggregation ──
    logger.info("Phase 5: Aggregating portfolio risk...")
    portfolio = aggregate_portfolio(dataset.merchants, predictions, probabilities)
    logger.info(
        f"  High risk: {portfolio['high_risk_count']}/{portfolio['total_merchants']} "
        f"({portfolio['high_risk_pct']}%), "
        f"Expected loss: ${portfolio['expected_loss_volume']:,.0f}"
    )

    # ── Phase 6: LLM Report ──
    logger.info("Phase 6: Generating LLM report...")
    report_text = generate_report(dataset, portfolio, metrics, feature_importances)
    output_path = save_report(report_text)
    logger.info(f"  Report saved to {output_path} ({len(report_text)} chars)")

    logger.info("Pipeline complete.")


if __name__ == "__main__":
    main()
