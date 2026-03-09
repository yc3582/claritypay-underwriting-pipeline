"""
LLM report generation: use Anthropic Claude API to produce an underwriting report.

The report is generated FROM pipeline outputs (not a static template).
We feed the LLM structured data from all previous phases and ask it to
write a 1-2 page risk report for the underwriting team.

Data fed to the LLM:
- Portfolio summary (Phase 5): risk counts, expected loss, percentages
- High-risk merchant details (Phase 5): names, volumes, probabilities
- Model performance (Phase 4): accuracy, recall, feature importances
- PDF context (Phase 1d): sample merchant summary text
- Scrape context (Phase 1e): ClarityPay company info, partners, stats

The LLM acts as a report WRITER, not a decision maker. All analysis
is already done by the pipeline — the LLM synthesizes it into prose.
"""

import logging
import os

import anthropic

from ingestion.validators import CollatedDataset

logger = logging.getLogger(__name__)

# Model to use for report generation. Haiku is fast and cheap,
# sufficient for structured report writing from provided data.
MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """\
You are a risk analyst at ClarityPay, a Buy Now Pay Later (BNPL) fintech company.
Write a concise underwriting risk report (1-2 pages) for the internal risk team.

The report should be professional, data-driven, and actionable. Include:
1. Executive Summary: portfolio size, overall risk level, key headline numbers
2. Portfolio Risk Overview: high-risk vs low-risk breakdown, expected loss exposure
3. High-Risk Merchants: list the flagged merchants with key details and why they're concerning
4. Model Performance: brief note on model accuracy and limitations
5. Key Risk Factors: what features drive risk predictions
6. Red Flags & Recommendations: specific concerns and suggested actions
7. Limitations & Next Steps: what would improve the analysis

Use markdown formatting. Be specific with numbers — don't just say "some merchants are risky",
say "19 of 50 merchants (38%) are flagged as high risk." Reference the data provided.

Remember ClarityPay's philosophy: risk is acceptable if it is PRICED — understood and quantified.
The goal is not to reject merchants but to understand and price the risk appropriately.
"""


def build_prompt_context(
    dataset: CollatedDataset,
    portfolio: dict,
    model_metrics: dict,
    feature_importances: list[tuple[str, float]],
) -> str:
    """
    Assemble pipeline outputs into a structured text block for the LLM.

    We provide enough data for a meaningful report but not so much that
    the LLM gets overwhelmed. Key strategy:
    - Full portfolio summary (numbers, not raw data)
    - All high-risk merchants with details
    - Top 5 low-risk merchants for contrast
    - Model performance and feature importances
    - PDF and scrape context as supplementary info
    """
    sections = []

    # --- Portfolio Summary ---
    sections.append("## PORTFOLIO SUMMARY")
    sections.append(f"Total merchants: {portfolio['total_merchants']}")
    sections.append(f"High risk: {portfolio['high_risk_count']} ({portfolio['high_risk_pct']}%)")
    sections.append(f"Low risk: {portfolio['low_risk_count']}")
    sections.append(f"Total monthly volume: ${portfolio['total_monthly_volume']:,}")
    sections.append(f"Expected loss volume (volume at risk): ${portfolio['expected_loss_volume']:,.0f} ({portfolio['expected_loss_pct']}%)")
    sections.append("")

    # --- High-Risk Merchants ---
    sections.append("## HIGH-RISK MERCHANTS (model-predicted)")
    for m in portfolio["high_risk_merchants"]:
        # Find full merchant data for extra context
        full = next((x for x in dataset.merchants if x.merchant_id == m["merchant_id"]), None)
        line = (
            f"- {m['merchant_id']} {m['name']}: "
            f"volume=${m['monthly_volume']:,}, "
            f"prob={m['prob_high_risk']}"
        )
        if full:
            line += (
                f", country={full.country}, "
                f"risk_flag={full.internal_risk_flag}, "
                f"disputes={full.dispute_count}/{full.transaction_count} txns"
            )
        sections.append(line)
    sections.append("")

    # --- Sample Low-Risk Merchants (for contrast) ---
    sections.append("## SAMPLE LOW-RISK MERCHANTS (top 5 by volume)")
    low_risk_sorted = sorted(portfolio["low_risk_merchants"], key=lambda x: -x["monthly_volume"])
    for m in low_risk_sorted[:5]:
        full = next((x for x in dataset.merchants if x.merchant_id == m["merchant_id"]), None)
        line = (
            f"- {m['merchant_id']} {m['name']}: "
            f"volume=${m['monthly_volume']:,}, "
            f"prob={m['prob_high_risk']}"
        )
        if full:
            line += (
                f", country={full.country}, "
                f"risk_flag={full.internal_risk_flag}, "
                f"disputes={full.dispute_count}/{full.transaction_count} txns"
            )
        sections.append(line)
    sections.append("")

    # --- Model Performance ---
    sections.append("## MODEL PERFORMANCE")
    sections.append(f"Model: Decision Tree (max_depth=3, class_weight=balanced)")
    sections.append(f"Train/test split: 80/20 stratified")
    sections.append(f"Accuracy: {model_metrics['accuracy']:.0%}")
    sections.append(f"High-risk recall: {model_metrics['high_risk_recall']:.0%}")
    sections.append(f"High-risk precision: {model_metrics['high_risk_precision']:.0%}")
    sections.append(f"High-risk F1: {model_metrics['high_risk_f1']:.0%}")
    sections.append("")
    sections.append("Feature importances:")
    for name, imp in feature_importances:
        if imp > 0:
            sections.append(f"  - {name}: {imp:.1%}")
        else:
            sections.append(f"  - {name}: 0% (not used by model)")
    sections.append("")

    # --- PDF Context (sample merchant summary) ---
    if dataset.pdf_summary:
        sections.append("## SAMPLE MERCHANT DOCUMENT (PDF extract)")
        sections.append(dataset.pdf_summary.raw_text)
        sections.append("")

    # --- Scrape Context (ClarityPay company info) ---
    if dataset.scrape_data:
        sections.append("## CLARITYPAY COMPANY CONTEXT (from website)")
        sections.append(f"URL: {dataset.scrape_data.url}")
        sections.append(f"Value propositions: {', '.join(dataset.scrape_data.value_propositions)}")
        sections.append(f"Partners: {', '.join(dataset.scrape_data.partners)}")
        sections.append(f"Public stats: {dataset.scrape_data.stats}")
        sections.append("")

    return "\n".join(sections)


def generate_report(
    dataset: CollatedDataset,
    portfolio: dict,
    model_metrics: dict,
    feature_importances: list[tuple[str, float]],
) -> str:
    """
    Call the Anthropic Claude API to generate the underwriting report.

    Args:
        dataset: Full collated dataset (merchants + PDF + scrape)
        portfolio: Portfolio summary dict from aggregate_portfolio()
        model_metrics: Evaluation metrics dict from evaluate_model()
        feature_importances: List of (feature_name, importance) tuples

    Returns:
        The generated report text (markdown formatted).
    """
    # Build the data context for the prompt
    context = build_prompt_context(dataset, portfolio, model_metrics, feature_importances)

    logger.info(f"Built prompt context: {len(context)} characters")

    # Create the Anthropic client (reads ANTHROPIC_API_KEY from env)
    client = anthropic.Anthropic()

    user_message = (
        "Using the pipeline data below, write the underwriting risk report.\n\n"
        f"{context}"
    )

    logger.info(f"Calling {MODEL} for report generation...")

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_message},
            ],
        )
    except anthropic.APIError as e:
        logger.error(f"Anthropic API call failed: {e}")
        raise

    # Extract text from the response
    report_text = message.content[0].text

    logger.info(
        f"Report generated: {len(report_text)} characters, "
        f"usage: {message.usage.input_tokens} input tokens, "
        f"{message.usage.output_tokens} output tokens"
    )

    return report_text


def save_report(report_text: str, output_path: str = "output/risk_report.md") -> str:
    """Save the generated report to a file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w") as f:
        f.write(report_text)

    logger.info(f"Report saved to {output_path}")
    return output_path
