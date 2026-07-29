"""
SQLAlchemy ORM model for persisting health risk scores.

WHY A SEPARATE TABLE (NOT ADDING TO EXISTING exogenous_covariates):
We deliberately keep health risk scores in their own table so the blast radius
of any schema change is limited to this bounded context. The existing
``exogenous_covariates`` table stores raw external data (humidity, rain, trends).
This new table stores DERIVED scores that combine those inputs into an actionable
risk value. Different concerns, different tables.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class HealthRiskScoreModel(Base):
    """
    Persists one computed risk score for one disease at one location and time.

    Each row represents the output of a RiskScoringStrategy.calculate_risk()
    call that was deemed worth persisting (e.g. for audit, dashboards, or
    trend analysis). The unique constraint on (pincode, disease_category,
    computed_at) prevents duplicate scores for the same place/disease/time
    being inserted accidentally.
    """

    __tablename__ = "health_risk_scores"

    id = Column(Integer, primary_key=True, index=True)

    # Location: which postal code this score applies to
    pincode = Column(String, index=True, nullable=False)

    # Disease category stored as the Enum's string value (e.g. "dengue")
    disease_category = Column(String, nullable=False)

    # The numeric risk score, 0.0 to 100.0 (matching trend_score scale)
    score = Column(Float, nullable=False)

    # Confidence level: "real_data", "fallback_neutral", or "stale_cache"
    confidence = Column(String, nullable=False)

    # When this score was computed
    computed_at = Column(DateTime(timezone=True), nullable=False)

    # Full trace of raw inputs that produced this score, stored as JSON
    contributing_factors = Column(JSON, nullable=True)

    # Prevent duplicate scores for the same location, disease, and time
    __table_args__ = (
        UniqueConstraint(
            "pincode", "disease_category", "computed_at",
            name="uix_health_risk_score_pincode_disease_time",
        ),
    )
