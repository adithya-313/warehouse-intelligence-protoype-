"""
V1 implementation of RiskScoringStrategy — a transparent formula-based scorer.

WHY A PLACEHOLDER FIRST:
This file exists to prove the interface works end-to-end before we invest in
the real formula. The real scoring logic (combining trend_score + weather
anomaly into a weighted risk value) will be implemented in the very next step.
"""

from datetime import datetime, timezone

from app.health_risk.domain.disease_category import DiseaseCategory
from app.health_risk.domain.risk_score import RiskScore
from app.health_risk.domain.scoring_strategy import RiskScoringStrategy


class TransparentFormulaScorer(RiskScoringStrategy):
    """
    V1 scorer that returns a neutral placeholder score.

    TODO(Step 2): Replace this placeholder with real scoring logic.
    The real formula will:
      1. Use trend_score as the baseline (weighted ~60%).
      2. Add humidity/rain anomaly bonus (weighted ~40%) when weather
         deviates significantly from seasonal norms.
      3. Clamp the result to the 0.0-100.0 range.
      4. Return confidence="real_data" when all inputs are present, or
         "fallback_neutral" when any input is None.
    """

    def calculate_risk(
        self,
        pincode: str,
        disease_category: DiseaseCategory,
        trend_score: float | None,
        humidity_percent: float | None,
        rain_mm: float | None,
    ) -> RiskScore:
        """
        Placeholder: always returns score=50.0 with confidence=fallback_neutral.

        Args:
            pincode:            Location postal code.
            disease_category:   Which disease to score.
            trend_score:        Search trend intensity (0.0-100.0), or None.
            humidity_percent:   Relative humidity percentage, or None.
            rain_mm:            Precipitation in millimetres, or None.

        Returns:
            A RiskScore with score=50.0 and confidence="fallback_neutral".
        """
        return RiskScore(
            pincode=pincode,
            disease_category=disease_category,
            score=50.0,
            confidence="fallback_neutral",
            computed_at=datetime.now(timezone.utc),
            contributing_factors={
                "trend_score": trend_score,
                "humidity_percent": humidity_percent,
                "rain_mm": rain_mm,
            },
        )
