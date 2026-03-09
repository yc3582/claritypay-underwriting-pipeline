# AI Usage Documentation

## Tools Used

- **Claude Opus 4.6 via Claude Code** (Anthropic's CLI agent) — used throughout as a pair-programming tutor for architecture, coding, debugging, and learning ML concepts.
- **Claude Haiku 4.5** (via Anthropic API) — used within the pipeline itself to generate the underwriting report from structured pipeline outputs.

## How AI Was Used

AI was used as a **teaching partner and coding assistant**. Every piece of code was explained line-by-line before or after implementation. I made decisions about architecture, trade-offs, and scope — Claude helped me understand the options and implement them.

### My Role vs. AI's Role

| Area | My contribution | AI's contribution |
|------|----------------|-------------------|
| **Scope & priorities** | Decided what to build, what to skip, when to simplify | Suggested approaches, flagged trade-offs |
| **Architecture** | Approved structure, questioned design choices | Proposed directory layout, module boundaries |
| **Data decisions** | Chose thresholds, validated assumptions against data | Explained statistical implications, ran distribution analysis |
| **ML concepts** | Asked questions, challenged assumptions | Taught train/test splits, class imbalance, precision/recall |
| **Code** | Reviewed every line, caught bugs, requested changes | Wrote implementation following discussed approach |
| **Testing** | Specified what to test, verified coverage | Wrote test cases, fixed signature mismatches |
| **Documentation** | Decided what to document, wrote this file | Drafted README, REPORT based on accumulated decisions |

## Phase-by-Phase Usage

### Phase 0: Project Setup
- Discussed project structure and tech stack choices (uv vs poetry vs pip+venv).
- AI explained why uv is preferred for modern Python projects.

### Phase 1: Data Ingestion (5 sources)
- **CSV**: AI taught Pydantic validation concepts (BaseModel, Field, Optional, Literal). Wrote ingestion following fetch->parse->validate pattern. I walked through every line.
- **Mock API**: AI wrote FastAPI server + httpx client. I verified the risk flag distribution (22 low / 21 medium / 7 high) made sense.
- **REST Countries**: I questioned what fields to extract — assignment says "e.g." not "must." Decided region + subregion only. Discussed caching strategy (dict vs lru_cache vs Redis).
- **PDF**: AI initially proposed structured field parsing. I pushed back — checked assignment, found structured parsing is optional. Simplified to raw text only. The PDF had garbled text rendering; AI discovered an x-position reset technique to reconstruct lines from character positions. I requested a variable trace-through to understand the algorithm.
- **Scrape**: First attempt pulled 21 junk results for partners (all img alt texts). Investigated HTML structure together, refined to use "Proud Partner" text nodes. I flagged that hardcoded stat_patterns wasn't truly "scraping" — led to dynamic discovery via regex.

### Phase 2: Data Collation
- Discussed schema design: two-model approach (CollatedMerchant per-merchant + CollatedDataset wrapper with supplementary context). I asked why pandas merge was overkill — AI explained the extra conversion steps vs. simple dict lookup for 50 merchants.
- Optional fields for external sources (None = "data unavailable") — I asked about alternatives.

### Phase 3: Feature Engineering
- AI taught core concepts: feature engineering purpose, data leakage, encoding strategies.
- 5 key decisions discussed with alternatives before any code was written: target variable (binary vs regression), risk threshold (0.1% — chosen after analyzing the actual dispute rate distribution), feature set (7 features), categorical encoding (ordinal vs one-hot), model type (decision tree vs logistic regression vs random forest).
- I questioned why geography features would matter — discussed real-world reasons vs. our simulated data. Decided to include because the assignment suggests it and the tree will ignore if not predictive.
- Volume band thresholds were initially set too high (100k/300k → 36/13/1 split). Data inspection revealed the median is 73k. Fixed to tercile-based boundaries (51k/95k → 16/18/16 split).

### Phase 4: Risk Model
- AI taught train/eval split, stratified sampling, and evaluation metrics (precision, recall, F1).
- **Key learning moment**: First model run without class_weight predicted everything as low risk (0% high-risk recall, 70% accuracy). AI explained this is a classic class imbalance problem. Fix: single parameter `class_weight="balanced"`. Result: 90% accuracy, 67% recall, 100% precision.
- I questioned why risk_flag_encoded dominates at 76% importance — discussed that with 50 samples, the tree is conservative and picks the strongest 1-2 features.
- I caught a docstring reference to "decisions.md D26" (a non-submitted file) — fixed to inline the rationale.

### Phase 5: Portfolio Aggregation
- AI explained expected loss as volume-weighted probability. I asked what `monthly_volume * prob_high_risk` actually means — discussed it as "risk-adjusted exposure" with concrete dollar examples.

### Phase 6: LLM Report Generation
- AI wrote the report generator. Model choice: Haiku 4.5 (fast, cheap, sufficient for structured writing).
- Prompt design: system prompt defines analyst role + 7-section report structure. User message provides assembled pipeline data. The LLM acts as a **report writer**, not a decision maker — all analysis is done by the pipeline.
- Encountered API key loading issue (`source .env` doesn't work in uv subshell). Fixed with `export $(cat .env | xargs)`.

### Phase 7: Tests & Governance
- AI wrote 42 tests across 3 files. Had to fix initial version — assumed wrong function signatures (parse_row returns dict not MerchantCSVRow, validate_rows returns list not tuple). Fixed by reading the actual source code.
- Logging was built into every module during Phases 1-6 (not added retroactively). Phase 7 review found 2 gaps: mock_api_server.py lacked a logger entirely, generate_report.py lacked error handling around the API call. Both fixed.

### Phase 8: Final Deliverables
- AI drafted README.md, REPORT.md, and this file based on accumulated decisions and notes. I reviewed and approved content.
- AI wrote run_pipeline.py as the main entry point (glue code calling existing functions in sequence).

## Key Prompts (Paraphrased)

These represent the types of prompts I used, not exact transcripts:

1. **Architecture**: "Let's set up the project. Read the assignment README and propose a structure."
2. **Teaching**: "Explain what stratified sampling is and why we need it for our 16/34 class split."
3. **Decision-making**: "What are the alternatives for the risk threshold? Show me the distribution at different values."
4. **Challenge**: "Why would geography features affect risk prediction? Our data is simulated."
5. **Debugging**: "The model predicts everything as low risk with 70% accuracy. What's wrong?"
6. **Scope control**: "Is PDF structured parsing required? Check the assignment."
7. **Documentation**: "Log decision D27 — we added class_weight=balanced. Note the alternatives and why."

## What I Learned

- **Class imbalance is real**: A model can be 70% "accurate" while being completely useless (predicts majority class only). The fix was a single parameter, but understanding *why* it works matters.
- **Precision vs. recall trade-off**: For underwriting, 100% precision (every flag is real) with 67% recall (miss some risky merchants) is a reasonable starting point. Missing a risky merchant is bad, but false alarms erode trust in the system.
- **Feature engineering matters more than model complexity**: Our simple 3-depth tree gets 90% accuracy because the features (especially risk_flag) are informative. A deeper or fancier model wouldn't help much with 50 samples.
- **Data leakage is subtle**: Using dispute_rate as both a feature and the basis for the target label would be circular. The pipeline avoids this by computing the target separately from features.
- **LLMs are writers, not analysts**: The report generation step feeds the LLM structured data and asks it to synthesize prose. All quantitative analysis happens in the pipeline. The LLM adds readability, not intelligence.

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
