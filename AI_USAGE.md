# AI Usage Documentation

## Tools Used

- **Claude Opus 4.6 via Claude Code** (Anthropic's CLI agent) — pair-programming tutor for architecture, coding, debugging, and learning ML concepts.
- **Claude Haiku 4.5** (via Anthropic API) — used within the pipeline to generate the underwriting report from structured pipeline outputs.

## How AI Was Used

I used AI as a **teaching partner and coding assistant**. My workflow: discuss the approach and alternatives first, make a decision, then implement with AI assistance. I reviewed every line of code and requested line-by-line walkthroughs to make sure I could explain everything in the live session.

### My Role vs. AI's Role

| Area | What I did | What AI did |
|------|-----------|-------------|
| **Scope & priorities** | Decided what to build, what to skip, when to simplify | Suggested approaches, flagged trade-offs |
| **Architecture** | Approved structure, questioned design choices | Proposed directory layout, module boundaries |
| **Data decisions** | Chose thresholds, validated assumptions against data | Explained statistical implications, ran distribution analysis |
| **ML concepts** | Asked questions, challenged assumptions | Taught train/test splits, class imbalance, precision/recall |
| **Code** | Reviewed every line, caught bugs, requested changes | Wrote implementation following discussed approach |
| **Testing** | Specified what to test, verified coverage | Wrote test cases, fixed signature mismatches |

## Phase-by-Phase Detail

### Phase 0: Project Setup
Discussed project structure and tech stack. I chose uv over poetry/pip+venv after understanding the trade-offs.

### Phase 1: Data Ingestion (5 sources)
- **CSV**: Learned Pydantic validation concepts, implemented fetch->parse->validate pattern with AI assistance.
- **Mock API**: Implemented FastAPI server + httpx client. I verified the risk flag distribution (22/21/7) made sense for downstream modeling.
- **REST Countries**: I scoped down extraction to region + subregion only — the assignment says "e.g." not "must." Chose dict cache over lru_cache/Redis for simplicity (23 unique countries).
- **PDF**: AI initially proposed structured field parsing. **I pushed back** — checked the assignment, which says structured parsing is optional. Simplified to raw text extraction. When the PDF rendered garbled text, AI found an x-position reset technique; I requested a variable trace-through to understand the algorithm before accepting it.
- **Scrape**: First attempt pulled 21 junk partner results. After investigating the HTML structure, refined to use "Proud Partner" text nodes. **I flagged** that the initial hardcoded stat_patterns wasn't truly "scraping" — this led to rewriting with dynamic regex discovery.

### Phase 2: Data Collation
I chose a two-model schema (CollatedMerchant + CollatedDataset) over alternatives (flat model, plain dicts, DataFrame). Asked AI to explain why pandas merge was overkill — understood that simple dict lookup is sufficient for 50 merchants with exact-match keys.

### Phase 3: Feature Engineering
Learned feature engineering concepts (data leakage, encoding strategies) with AI assistance. **I made 5 key decisions before any code was written**: target variable (binary), risk threshold (0.1% — after inspecting the actual dispute rate distribution), feature set (7 features), encoding strategy (ordinal for risk_flag, label for subregion), model type (decision tree).

Two moments where I challenged the AI's suggestions:
- **Geography features**: I questioned why is_uk/subregion would matter when the data is simulated. We decided to include them because the assignment explicitly suggests "geography" and the tree will ignore them if not predictive.
- **Volume band thresholds**: Initial values (100k/300k) produced a 36/13/1 split. I inspected the data, found the median is 73k, and we switched to tercile-based boundaries (51k/95k → 16/18/16).

### Phase 4: Risk Model
Learned train/eval split, stratified sampling, and evaluation metrics with AI assistance.

**Key debugging moment**: The first model run predicted everything as low risk (0% recall, 70% accuracy). AI explained this as a class imbalance problem. The fix was a single parameter (`class_weight="balanced"`), bringing results to 90% accuracy, 67% recall, 100% precision — not heavy tuning.

I also questioned why risk_flag_encoded dominates at 76% importance, and caught a docstring referencing a non-submitted file ("decisions.md D26") — fixed it to inline the rationale.

### Phase 5: Portfolio Aggregation
Implemented expected loss as volume-weighted probability. I asked what `monthly_volume * prob_high_risk` actually represents — understood it as "risk-adjusted exposure" (a $100K merchant at 75% probability contributes $75K to expected loss).

### Phase 6: LLM Report Generation
Implemented the report generator with AI assistance. Key design choice: the LLM acts as a **report writer**, not a decision maker — all quantitative analysis is done by the pipeline, the LLM synthesizes it into prose.

### Phase 7: Tests & Governance
Wrote 42 tests across 3 files with AI assistance. The initial test version had wrong assumptions about function signatures — caught by reading the actual source code. Logging was built into every module during Phases 1-6 (not retroactively). A review pass found 2 gaps and fixed them.

### Phase 8: Final Deliverables
Wrote run_pipeline.py (orchestration), README, REPORT, and this document with AI assistance. I reviewed and edited all content.

## Key Prompts (Paraphrased)

These represent the types of prompts I used, not exact transcripts:

1. **Architecture**: "Read the assignment README and propose a structure."
2. **Teaching**: "Explain stratified sampling and why we need it for our 16/34 class split."
3. **Decision-making**: "What are the alternatives for the risk threshold? Show me the distribution at different values."
4. **Challenge**: "Why would geography features affect risk prediction? Our data is simulated."
5. **Debugging**: "The model predicts everything as low risk with 70% accuracy. What's wrong?"
6. **Scope control**: "Is PDF structured parsing required? Check the assignment."

## What I Learned

- **Class imbalance is real**: A model can be 70% "accurate" while being completely useless (predicts majority class only). The fix was a single parameter, but understanding *why* it works matters.
- **Precision vs. recall trade-off**: For underwriting, 100% precision (every flag is real) with 67% recall (miss some risky merchants) is a reasonable starting point. Missing a risky merchant is bad, but false alarms erode trust.
- **Feature engineering matters more than model complexity**: A simple 3-depth tree gets 90% accuracy because the features are informative. A fancier model wouldn't help much with 50 samples.
- **Data leakage is subtle**: Using dispute_rate as both a feature and the basis for the target label would be circular. The pipeline avoids this by computing them separately.
- **LLMs are writers, not analysts**: The report generation step feeds structured data to the LLM and asks it to synthesize prose. All quantitative analysis happens in the pipeline.

## LLM Report Generation Prompt

The pipeline uses Claude Haiku 4.5 to generate the underwriting report. The full prompts are in `reporting/generate_report.py`. Here is the system prompt:

```
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
```

The user message provides assembled pipeline data in labeled sections: portfolio summary (counts, volumes, expected loss), all high-risk merchants with details (country, risk flag, disputes), top 5 low-risk merchants for contrast, model metrics (accuracy, recall, precision, feature importances), PDF extract text, and scraped ClarityPay company context.

## Ethical Considerations

- AI was used transparently — this document exists to show exactly how.
- No AI-generated content was passed off as original analysis. The model's predictions and the LLM's report are clearly labeled as machine-generated outputs.
- I understand every line of code in the codebase and can explain it in a walkthrough. AI accelerated implementation but did not replace understanding.
