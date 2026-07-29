"""
V2 implementation of RiskScoringStrategy — real weighted-formula scorer.

WHAT THIS SCORER DOES:
Combines trend_score (Google search interest for symptom keywords) and
weather_anomaly (humidity + rain deviation from normal) into a single
0-100 risk score using a transparent, documented formula.

WHY THESE WEIGHTS (60% TREND, 40% WEATHER):
  - 60% trend: Google search trends are a LEADING indicator. People search
    "dengue symptoms" or "fever medicine" BEFORE visiting a pharmacy. This
    gives us 1-3 days of early warning before prescription data catches up.
  - 40% weather: Weather anomalies are a CONFIRMING indicator. They explain
    WHY a disease is spreading (monsoon → mosquito breeding → dengue) and
    help distinguish real outbreaks from search noise (e.g. a news report
    causing panic searches without actual cases).

The weights are deliberately simple multiples of 10 so the formula is
easy to explain to non-technical stakeholders: "60% of the score comes
from what people are searching online, 40% from current weather data."
"""

from datetime import datetime, timezone

from app.health_risk.domain.disease_category import DiseaseCategory
from app.health_risk.domain.risk_score import RiskScore
from app.health_risk.domain.scoring_strategy import RiskScoringStrategy
from app.health_risk.domain.weather_anomaly import calculate_weather_anomaly

# ---------------------------------------------------------------------------
# Formula weights — documented constants, not buried literals.
# These live at module level so they can be inspected and tuned without
# reading through the function body.
# ---------------------------------------------------------------------------
TREND_WEIGHT: float = 0.6     # 60% — leading indicator (search behaviour)
WEATHER_WEIGHT: float = 0.4   # 40% — confirming indicator (environmental)

FALLBACK_SCORE: float = 50.0  # Neutral middle value when all data is missing


class TransparentFormulaScorer(RiskScoringStrategy):
    """
    V2 scorer combining trend + weather into a weighted risk score.

    The formula is:
        final_score = (trend_score * 0.6) + (weather_anomaly * 0.4)

    When data is missing, the scorer gracefully degrades:
        - trend_score is None → use weather only, confidence="fallback_neutral"
        - both trend and weather are None → score=50.0, confidence="fallback_neutral"
        - all data present              → confidence="real_data"
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
        Calculate a health risk score by combining trend and weather data.

        The method never crashes on missing data — it degrades gracefully
        and reports the confidence level so callers know whether the score
        is based on real data or fallback defaults.
        """
        # ------------------------------------------------------------------
        # Step 1: Calculate weather anomaly from raw humidity + rain.
        # This is always computed first because even if trend is missing,
        # we want the weather component ready.
        # ------------------------------------------------------------------
        weather_anomaly: float = calculate_weather_anomaly(
            humidity_percent=humidity_percent,
            rain_mm=rain_mm,
        )

        # ------------------------------------------------------------------
        # Step 2: Build the contributing_factors "receipt" — a full trace
        # of every raw input that went into this score. This is the
        # traceability guarantee from the Step 1 scaffold design.
        # ------------------------------------------------------------------
        contributing_factors: dict = {
            "trend_score": trend_score,
            "humidity_percent": humidity_percent,
            "rain_mm": rain_mm,
            "weather_anomaly": weather_anomaly,
        }

        # ------------------------------------------------------------------
        # Step 3: Determine which data is available and calculate the score.
        #
        # Three cases:
        #   A. Both trend and weather available → weighted average, real_data
        #   B. Only weather available → weather alone, fallback_neutral
        #   C. Neither available → neutral score, fallback_neutral
        # ------------------------------------------------------------------

        if trend_score is not None:
            # ------------------------------------------------------------------
            # Case A: All data available. Use the standard weighted formula.
            # confidence="real_data" tells downstream systems this score is
            # based on fresh, real-world inputs.
            #
            # Formula:
            #   final = (trend_score * 0.6) + (weather_anomaly * 0.4)
            #
            # Both components are already on the 0-100 scale, so the weighted
            # average stays within the valid range automatically.
            # ------------------------------------------------------------------
            final_score: float = (
                trend_score * TREND_WEIGHT + weather_anomaly * WEATHER_WEIGHT
            )
            confidence: str = "real_data"

        elif humidity_percent is not None or rain_mm is not None:
            # ------------------------------------------------------------------
            # Case B: Only weather data is available (trend_score is None but
            # at least one weather input was provided). Use weather alone.
            #
            # The weather_anomaly is already a 0-100 score computed from
            # whatever weather inputs were available (if one was None, the
            # anomaly function returned neutral for that dimension).
            #
            # confidence="fallback_neutral" tells downstream systems that
            # search trend data was missing and the score is less reliable.
            # ------------------------------------------------------------------
            final_score = weather_anomaly
            confidence = "fallback_neutral"

        else:
            # ------------------------------------------------------------------
            # Case C: No data at all — both trend and weather are missing.
            # Return a neutral score of 50.0 (middle of 0-100 range). The
            # procurement router checks "score > 70.0" for alerts, so 50.0
            # will NOT trigger a false-positive disease wave alert.
            #
            # This is better than crashing the background ingestion job,
            # which would delay ALL scores for ALL pincodes, not just this one.
            # ------------------------------------------------------------------
            final_score = FALLBACK_SCORE
            confidence = "fallback_neutral"

        # ------------------------------------------------------------------
        # Step 4: Construct and return the validated RiskScore.
        # The RiskScore.__post_init__ will validate the 0-100 range for us.
        # ------------------------------------------------------------------
        return RiskScore(
            pincode=pincode,
            disease_category=disease_category,
            score=round(final_score, 1),
            confidence=confidence,
            computed_at=datetime.now(timezone.utc),
            contributing_factors=contributing_factors,
        )
