# Written Report: Assumptions, Trade-offs & Production Considerations

## Assumptions

### Data Assumptions
- **CSV is the source of truth** for merchant identity (merchant_id, name, country, volume, disputes, transactions). All other sources enrich this base.
- **Non-UK merchants lack registration numbers.** Empty `registration_number` fields are treated as None, not invalid.
- **dispute_rate = dispute_count / transaction_count.** Merchants with 0 transactions get rate 0 (not undefined).
- **Mock API risk flags correlate with dispute behavior.** The server assigns flags based on dispute rate thresholds (>=0.15% high, >=0.05% medium, else low). This simulates an internal underwriting system that has already assessed each merchant.

### Model Assumptions
- **Binary classification target**: dispute_rate >= 0.1% = high risk. This threshold was chosen empirically — it produces a 16/34 (32%/68%) class split, balanced enough for the model to learn while selective enough to be meaningful.
- **7 features are sufficient** for 50 samples. More features would risk overfitting. The decision tree naturally selects the most predictive features (risk_flag_encoded at 76%, avg_ticket_size at 24%).
- **Geographic features included despite low signal**: The assignment suggests "geography" as a feature. Decision tree will ignore features that don't improve splits — no downside to including them, and they demonstrate the pipeline handles geographic enrichment.

### Pipeline Assumptions
- **Companies House API: skipped (optional).** The assignment notes this is optional and says to "document a fallback." Our fallback: UK merchants with `registration_number` values are validated via Pydantic (format check) but not verified against Companies House. In production, we would integrate the Companies House API to verify company status, incorporation date, and beneficial ownership. The pipeline architecture supports this — `collate_merchant()` would accept an additional data source and merge it into `CollatedMerchant` via a new optional field group.
- **PDF is supplementary context**, not per-merchant data. The sample PDF covers only M001; it's attached to the CollatedDataset and fed to the LLM for report context.
- **Scrape data is company-level context**, not per-merchant. Value propositions, partners, and stats from claritypay.com inform the report but don't enter the model as features.
- **External APIs may fail gracefully.** Optional fields (API risk flag, country region, PDF text, scrape data) default to None if their source is unavailable. The pipeline continues with whatever data it has.

## Trade-offs

### Simplicity vs. Sophistication

| Choice | Trade-off | Why |
|--------|-----------|-----|
| Decision tree (not random forest) | Less accurate but more interpretable | 50 samples — interpretable rules are more valuable than marginal accuracy gains. Can explain exact splits in walkthrough. |
| max_depth=3 | Misses some patterns | Prevents overfitting on 50 samples. Deeper tree memorizes noise. |
| class_weight=balanced (not SMOTE) | Less control over resampling | Single parameter vs. adding a library. With 50 samples, SMOTE would generate synthetic data from very few examples — risky. |
| Binary target (not regression) | Loses granularity | Regression on dispute_rate (tiny floats 0.0001–0.0025) or dispute_count (integers 0–8) would be harder to model and less useful for underwriting decisions. |
| Volume-weighted expected loss (not Monte Carlo) | Rough approximation | Sufficient for portfolio summary. Production would add loss-given-dispute multiplier and confidence intervals. |
| Dict cache for countries (not Redis) | Single-run only | 23 unique countries, pipeline runs once. Production would use persistent cache. |
| Raw PDF text (not structured parsing) | Less structured | Assignment says structured parsing is optional. Raw text is fed to LLM which interprets it. |

### 67% Recall — Acceptable?

The model misses ~33% of truly high-risk merchants. This is a known limitation of a depth-3 tree on 50 samples. We chose 100% precision over higher recall — every flagged merchant is genuinely risky, which means the risk team trusts the flags. The 12 merchants predicted at probability 0.757 (Tier 2) capture some of the borderline cases. In production, I would:
1. Increase training data (more merchants = better recall)
2. Try ensemble methods (Random Forest, XGBoost)
3. Add a "medium risk" tier for merchants near the decision boundary

## Production Considerations

### Idempotency

The current pipeline produces the same output given the same inputs (CSV data, mock API seed, model random_state). To make it fully idempotent in production:

1. **Ingestion**: Each source fetch would check a hash of the source data (e.g., CSV file hash, API response hash). If unchanged since last run, skip re-ingestion. Store hashes in a metadata table.

2. **Collation**: Use a `pipeline_run_id` (timestamp or UUID) to version each collated dataset. If a run with identical input hashes already exists, return the cached result.

3. **Model training**: Pin the random_state (already done) and version the training data. Same data + same hyperparameters = same model. Store model artifacts with their training data hash.

4. **Report generation**: LLM output is non-deterministic (temperature > 0). For true idempotency, cache the report keyed by (model_version, portfolio_hash). Or set temperature=0 for near-deterministic output.

5. **Storage**: Use append-only storage (don't overwrite previous runs). Each run produces a versioned output directory: `output/run_<id>/`.

### Monitoring

- **Data drift**: Track distribution of incoming merchant volumes, dispute rates, and country mix. Alert if distribution shifts significantly from training data.
- **Model performance**: Log predictions vs. actual outcomes (once disputes are observed). Track precision/recall monthly.
- **Source health**: Monitor API response times, error rates, and data completeness. Alert if REST Countries or the internal API starts returning errors.
- **Report quality**: Sample LLM-generated reports for review. Track token usage for cost monitoring.

### Retraining

- **Trigger**: Retrain when (a) new merchant data arrives, (b) model performance degrades below thresholds, or (c) quarterly scheduled review.
- **Process**: Automated pipeline that re-runs feature engineering + training on updated data, evaluates against held-out set, and promotes model if metrics improve.
- **Rollback**: Keep previous model version. If new model underperforms, revert to last known good.

### Governance

- **Audit trail**: Log every pipeline run with inputs, outputs, model version, and predictions. Store in append-only format.
- **Access control**: API keys in environment variables (not code). Model predictions and reports access-controlled to risk team.
- **Data retention**: Define retention policy for merchant data, model artifacts, and generated reports per regulatory requirements.
- **Bias review**: Periodically review whether geographic or demographic features introduce unfair bias in risk predictions.

### Scaling

The current pipeline processes 50 merchants in seconds. For production scale (thousands of merchants):
- Replace in-memory dict cache with Redis or database
- Parallelize API calls (async batch fetching)
- Use a job queue (Celery) for PDF processing
- Store collated data in a database rather than in-memory objects
- Consider batch prediction instead of per-merchant model calls
