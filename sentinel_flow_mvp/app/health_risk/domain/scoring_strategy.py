"""
Abstract contract for all health risk scoring approaches.

WHY AN INTERFACE (STRATEGY PATTERN):
The rest of the health_risk module should never care HOW a score is calculated.
Today we use a simple formula (TransparentFormulaScorer). Tomorrow we might
switch to an ML model, a rules engine, or an ensemble of both. As long as the
replacement implements this interface, nothing else in the system needs to change.

This is the classic Strategy pattern applied to domain scoring.
"""

from abc import ABC, abstractmethod

from app.health_risk.domain.disease_category import DiseaseCategory
from app.health_risk.domain.risk_score import RiskScore


class RiskScoringStrategy(ABC):
    """
    Contract that every scoring implementation must satisfy.

    Subclasses must implement ``calculate_risk``. The caller provides the
    raw inputs (trend data, weather data) and gets back a fully-constructed
    RiskScore. The subclass decides how to combine those inputs into the
    final score value.

    The method signature accepts ``float | None`` for each input so that a
    caller can pass whatever data it has without crashing -- the implementor
    decides how to handle missing values (e.g. return fallback_neutral if
    trend_score is None).
    """

    @abstractmethod
    def calculate_risk(
        self,
        pincode: str,
        disease_category: DiseaseCategory,
        trend_score: float | None,
        humidity_percent: float | None,
        rain_mm: float | None,
    ) -> RiskScore:
        """
        Calculate a health risk score from the given inputs.

        Args:
            pincode:            Location postal code.
            disease_category:   Which disease to score.
            trend_score:        Search trend intensity (0.0-100.0), or None if unavailable.
            humidity_percent:   Relative humidity percentage, or None if unavailable.
            rain_mm:            Precipitation in millimetres, or None if unavailable.

        Returns:
            A RiskScore object with all fields populated. The score will always
            be in the 0.0-100.0 range (enforced by RiskScore.__post_init__).

        Raises:
            ValueError: If the inputs cannot produce a valid score.
        """
        ...
