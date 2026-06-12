"""Fraud Detection ML Model Layer.

This module implements the Isolation Forest-based fraud detection engine.
It scores audit events for anomaly likelihood and returns risk assessments.

Domain-Driven Design context:
- Uses unsupervised learning (Isolation Forest) to detect outliers in
  transaction amounts and other event features.
- The model is fit with synthetic "normal" data on boot so it works immediately.
- In Phase 3, this will be replaced with a trained model from historical data.

FEATURE SCHEMA FOR PHASE 3:
    input_features = [
        "amount_value",           # Normalized transaction amount
        "event_type_encoded",     # One-hot encoded event category
        "entity_velocity",        # Number of events by this entity in last 24h
        "amount_velocity",        # Total amount by this entity in last 24h
        "hour_of_day",            # 0-23 hour when event occurred
        "day_of_week",            # 0-6 day of week
    ]
"""

import logging
import numpy as np
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)

# Risk threshold above which an event is flagged as anomalous
RISK_THRESHOLD = 0.85


class FraudDetectionModel:
    """Isolation Forest-based fraud detection engine.

    Fits on synthetic data at startup to provide immediate scoring capability.
    The contamination parameter defines the expected proportion of outliers (5%).
    """

    def __init__(self) -> None:
        """Initialize the Isolation Forest model with synthetic training data.

        Generates 100 synthetic "normal" transaction amounts between $10 and $500
        to create a baseline distribution. The model learns what "normal" looks like
        and flags transactions that deviate significantly from this pattern.
        """
        logger.info("Initializing FraudDetectionModel with synthetic training data...")

        # Generate 100 random normal transaction amounts between $10 and $500
        synthetic_amounts = np.random.uniform(low=10.0, high=500.0, size=100)

        # Reshape for sklearn: each sample is a 1D feature vector
        training_data = synthetic_amounts.reshape(-1, 1)

        # Instantiate and fit the Isolation Forest
        self.model = IsolationForest(
            contamination=0.01,
            random_state=42,
        )
        self.model.fit(training_data)

        logger.info("FraudDetectionModel initialized and fit with synthetic baseline.")

    def predict(
        self,
        event_type: str,
        amount_value: float,
    ) -> tuple:
        """Score a single audit event for fraud/anomaly likelihood.

        Args:
            event_type: The category of the auditable event.
            amount_value: The financial amount associated with the event.

        Returns:
            Tuple of (risk_score, is_flagged, reason).
            - risk_score: Normalized probability between 0.0 and 1.0.
            - is_flagged: True if risk_score exceeds the threshold.
            - reason: Human-readable explanation if flagged.
        """
        # Step 1: Check if there is a financial value to score
        if amount_value is None:
            return (0.0, False, "No financial value to score.")

        # Step 2: Prepare the feature vector (amount_value)
        feature_vector = np.array([[amount_value]])

        # Step 3: Get the anomaly score from Isolation Forest
        # Sklearn returns negative values for anomalies, positive for normal
        raw_decision_score = self.model.decision_function(feature_vector)[0]

        # Step 4: Normalize the decision score to a 0.0 - 1.0 risk scale
        # IsolationForest.decision_function typically returns values in [-0.5, 0.5]
        # We invert and normalize: lower decision score = higher risk
        normalized_score = 1.0 - (raw_decision_score + 0.5)
        normalized_score = max(0.0, min(normalized_score, 1.0))

        # Step 5: Determine if the event should be flagged
        is_flagged = normalized_score > RISK_THRESHOLD

        # Step 6: Generate a human-readable reason if flagged
        reason = None
        if is_flagged:
            # Explain WHY this transaction was flagged
            reason = (
                f"Transaction amount ${amount_value:.2f} is "
                f"significantly outside the normal range."
            )
            logger.warning(
                f"Fraud alert: event_type={event_type}, "
                f"amount=${amount_value:.2f}, risk={normalized_score:.4f}"
            )

        logger.debug(
            f"Fraud prediction: amount=${amount_value:.2f}, "
            f"risk={normalized_score:.4f}, flagged={is_flagged}"
        )

        return (normalized_score, is_flagged, reason)
