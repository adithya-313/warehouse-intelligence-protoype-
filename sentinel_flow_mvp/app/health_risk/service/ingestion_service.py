"""
Orchestrator that connects the full health_risk pipeline:
       trend_fetcher → weather query → scorer → database save

Call this function once per pincode during the background ingestion cycle.
It loops through every disease category we track and produces a RiskScore
for each one, saving it to the health_risk_scores table.

Each disease is processed independently inside a try/except so a failure
in one (e.g. Google Trends returns no data for leptospirosis) does NOT
prevent the other diseases from being scored and saved.
"""

import logging
from typing import List

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.config import ApplicationSettings
from app.health_risk.domain.disease_category import DiseaseCategory
from app.health_risk.domain.disease_keywords import DISEASE_KEYWORDS
from app.health_risk.domain.risk_score import RiskScore
from app.health_risk.domain.transparent_formula_scorer import TransparentFormulaScorer
from app.health_risk.infrastructure.db_models import HealthRiskScoreModel
from app.health_risk.infrastructure.trend_fetcher import fetch_trend_score
from app.infrastructure.models import ExogenousCovariateModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared scorer instance — the class is stateless, so we create it once.
# ---------------------------------------------------------------------------
_scorer = TransparentFormulaScorer()


def run_ingestion_for_pincode(
    pincode: str,
    db: Session,
    settings: ApplicationSettings,
) -> List[RiskScore]:
    """
    Run the full health_risk scoring pipeline for a single pincode.

    For EACH DiseaseCategory:
      1. Look up the Google Trends keyword (e.g. "dengue symptoms").
      2. Fetch the real-time trend score (or None if unavailable).
      3. Query the latest weather row (humidity + rain) from the existing
         exogenous_covariates table (or None values if no row exists).
      4. Calculate the combined risk score using TransparentFormulaScorer.
      5. Persist the result to the health_risk_scores table.
      6. Append the RiskScore object to the returned list.

    IMPORTANT: The feature flag (HEALTH_RISK_ENABLED + tenant flag) is NOT
    checked here. That check happens at the CALLER level (the Celery task
    or API route that invokes this function). This function does the actual
    work when called — it trusts the caller has already verified the flags.

    Args:
        pincode:  The postal code to fetch data for.
        db:       Active SQLAlchemy database session.
        settings: Application settings (used for Redis URL by fetch_trend_score).

    Returns:
        A list of RiskScore objects, one per disease category. The list will
        always have exactly 3 entries (one per disease) unless an unexpected
        error occurs that prevents ALL diseases from being processed.
    """
    results: List[RiskScore] = []

    # ------------------------------------------------------------------
    # Query the latest weather data for this pincode ONCE.
    # We reuse the same row for all diseases since weather is
    # location-specific, not disease-specific. If no row exists,
    # all weather inputs are None (scorer handles that gracefully).
    # ------------------------------------------------------------------
    latest_weather_row = _get_latest_weather_row(pincode, db)

    # Extract humidity and rain, defaulting to None if no row exists
    humidity_percent: float | None = (
        latest_weather_row.humidity_percent if latest_weather_row else None
    )
    rain_mm: float | None = (
        latest_weather_row.rain_mm if latest_weather_row else None
    )

    # ------------------------------------------------------------------
    # Process each disease independently. A failure in one disease
    # (e.g. trend fetch times out) must NOT stop the others.
    # ------------------------------------------------------------------
    for disease_category in DiseaseCategory:
        try:
            _process_single_disease(
                db=db,
                pincode=pincode,
                disease_category=disease_category,
                humidity_percent=humidity_percent,
                rain_mm=rain_mm,
                results=results,
            )
        except Exception as error:
            # Log the error and continue to the next disease.
            # An error here means the disease did NOT get scored this cycle,
            # but all other diseases still produce their scores.
            logger.exception(
                "Failed to process disease '%s' for pincode %s: %s",
                disease_category.value,
                pincode,
                error,
            )

    return results


def _get_latest_weather_row(
    pincode: str,
    db: Session,
) -> ExogenousCovariateModel | None:
    """
    Fetch the most recent ExogenousCovariateModel row for this pincode.

    Uses the same query pattern as app/main.py line 399-401:
      - Filter by pincode
      - Order by timestamp descending
      - Take the first (most recent) row

    Returns None if no row exists for this pincode (e.g. the covariate
    ingestion pipeline hasn't run for this location yet).
    """
    return (
        db.query(ExogenousCovariateModel)
        .filter(ExogenousCovariateModel.pincode == pincode)
        .order_by(desc(ExogenousCovariateModel.timestamp))
        .first()
    )


def _process_single_disease(
    db: Session,
    pincode: str,
    disease_category: DiseaseCategory,
    humidity_percent: float | None,
    rain_mm: float | None,
    results: List[RiskScore],
) -> None:
    """
    Process a single disease: fetch trend, calculate score, save, append.

    Extracted into its own function so the per-disease try/except in
    run_ingestion_for_pincode is clean and easy to read.
    """
    # ------------------------------------------------------------------
    # Step 1: Look up the search keyword for this disease.
    # If the keyword is missing (shouldn't happen, but defensive), log
    # and skip this disease with a clear error.
    # ------------------------------------------------------------------
    keyword = DISEASE_KEYWORDS.get(disease_category)
    if keyword is None:
        logger.error(
            "No keyword defined for disease category '%s'. Skipping.",
            disease_category.value,
        )
        return

    # ------------------------------------------------------------------
    # Step 2: Fetch the real-time Google Trends score.
    # Returns None if the data is unavailable (circuit breaker open,
    # network timeout, no search data for this keyword).
    # ------------------------------------------------------------------
    trend_score: float | None = fetch_trend_score(
        pincode=pincode,
        symptom_keyword=keyword,
    )

    # ------------------------------------------------------------------
    # Step 3: Calculate the combined risk score.
    # The scorer handles None inputs gracefully (returns fallback_neutral).
    # ------------------------------------------------------------------
    risk_score: RiskScore = _scorer.calculate_risk(
        pincode=pincode,
        disease_category=disease_category,
        trend_score=trend_score,
        humidity_percent=humidity_percent,
        rain_mm=rain_mm,
    )

    # ------------------------------------------------------------------
    # Step 4: Persist the result as a new row in health_risk_scores.
    # ------------------------------------------------------------------
    db_score_row = HealthRiskScoreModel(
        pincode=risk_score.pincode,
        disease_category=risk_score.disease_category.value,
        score=risk_score.score,
        confidence=risk_score.confidence,
        computed_at=risk_score.computed_at,
        contributing_factors=risk_score.contributing_factors,
    )
    db.add(db_score_row)
    db.commit()

    # ------------------------------------------------------------------
    # Step 5: Add to the result list for the caller.
    # ------------------------------------------------------------------
    results.append(risk_score)

    logger.info(
        "Scored '%s' for pincode %s: score=%.1f, confidence=%s, trend=%s, keyword='%s'.",
        disease_category.value,
        pincode,
        risk_score.score,
        risk_score.confidence,
        trend_score,
        keyword,
    )
