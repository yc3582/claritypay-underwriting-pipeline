"""
Train a decision tree classifier to predict merchant dispute risk.

This module takes the feature DataFrame and target labels from Phase 3
(feature_engineering.py) and:
1. Splits into train/test sets (stratified to preserve class balance)
2. Trains a DecisionTreeClassifier (max_depth=3 to prevent overfitting)
3. Evaluates with classification report (precision, recall, F1)
4. Returns the trained model + predictions for downstream use

Why decision tree? Handles mixed feature types naturally, produces interpretable
rules for underwriting review. Logistic regression needs feature scaling and
struggles with label-encoded categoricals. Random forest is less interpretable.
Why max_depth=3? 50 samples with 7 features — deeper tree memorizes noise.
Why stratified split? 16/34 class imbalance — random split could starve test set.
"""

import logging

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import classification_report

logger = logging.getLogger(__name__)


def split_data(
    X: pd.DataFrame,
    y: list[int],
    test_size: float = 0.2,
    random_state: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame, list[int], list[int]]:
    """
    Split features and target into train/test sets.

    Uses stratified sampling so both sets have the same ratio of
    high-risk vs low-risk merchants (~32%/68%).

    Args:
        X: Feature DataFrame (rows=merchants, columns=features)
        y: Target labels (0=low risk, 1=high risk)
        test_size: Fraction held out for testing (0.2 = 20% = ~10 merchants)
        random_state: Seed for reproducibility (same split every time)

    Returns:
        X_train, X_test, y_train, y_test
    """
    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=test_size,
        random_state=random_state,
        stratify=y,  # Preserve class balance in both sets
    )

    logger.info(
        f"Train/test split: {len(X_train)} train, {len(X_test)} test "
        f"(train high-risk: {sum(y_train)}, test high-risk: {sum(y_test)})"
    )

    return X_train, X_test, y_train, y_test


def train_model(
    X_train: pd.DataFrame,
    y_train: list[int],
    max_depth: int = 3,
    random_state: int = 42,
) -> DecisionTreeClassifier:
    """
    Train a decision tree classifier on the training data.

    Args:
        X_train: Training features
        y_train: Training labels
        max_depth: Maximum tree depth (limits complexity to prevent overfitting)
        random_state: Seed for reproducibility

    Returns:
        Fitted DecisionTreeClassifier
    """
    model = DecisionTreeClassifier(
        max_depth=max_depth,
        random_state=random_state,
        class_weight="balanced",  # Penalize minority class errors more
    )

    model.fit(X_train, y_train)

    logger.info(
        f"Trained DecisionTreeClassifier: max_depth={max_depth}, "
        f"actual depth={model.get_depth()}, "
        f"num leaves={model.get_n_leaves()}"
    )

    return model


def evaluate_model(
    model: DecisionTreeClassifier,
    X_test: pd.DataFrame,
    y_test: list[int],
) -> dict:
    """
    Evaluate the trained model on the test set.

    Prints a classification report (precision, recall, F1 per class).
    Returns a dict with key metrics for downstream use (portfolio, report).

    For underwriting, recall on class 1 (high risk) is most important:
    missing a risky merchant is worse than a false alarm.
    """
    y_pred = model.predict(X_test)

    # Classification report as a string (for logging)
    report_str = classification_report(
        y_test, y_pred,
        target_names=["low_risk", "high_risk"],
    )
    logger.info(f"Classification report:\n{report_str}")

    # Also get it as a dict (for programmatic use)
    report_dict = classification_report(
        y_test, y_pred,
        target_names=["low_risk", "high_risk"],
        output_dict=True,
    )

    # Extract key metrics
    accuracy = report_dict["accuracy"]
    high_risk_recall = report_dict["high_risk"]["recall"]
    high_risk_precision = report_dict["high_risk"]["precision"]
    high_risk_f1 = report_dict["high_risk"]["f1-score"]

    logger.info(
        f"Key metrics — Accuracy: {accuracy:.2f}, "
        f"High-risk recall: {high_risk_recall:.2f}, "
        f"High-risk precision: {high_risk_precision:.2f}, "
        f"High-risk F1: {high_risk_f1:.2f}"
    )

    return {
        "accuracy": accuracy,
        "high_risk_recall": high_risk_recall,
        "high_risk_precision": high_risk_precision,
        "high_risk_f1": high_risk_f1,
        "classification_report": report_str,
        "y_pred": y_pred.tolist(),
        "y_test": list(y_test),
    }


def predict_all(
    model: DecisionTreeClassifier,
    X: pd.DataFrame,
) -> np.ndarray:
    """
    Get predictions for ALL merchants (not just test set).

    Used by portfolio aggregation (Phase 5) and LLM report (Phase 6)
    to assign a risk band to every merchant.

    Also returns predicted probabilities so the portfolio step can
    estimate expected loss (not just hard labels).
    """
    predictions = model.predict(X)
    probabilities = model.predict_proba(X)

    high_risk_count = int(predictions.sum())
    logger.info(
        f"Full dataset predictions: {high_risk_count} high risk, "
        f"{len(predictions) - high_risk_count} low risk out of {len(predictions)}"
    )

    return predictions, probabilities
