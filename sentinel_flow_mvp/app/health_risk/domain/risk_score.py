"""
Pure domain object representing a calculated health risk score.

WHY THIS IS A PLAIN DATACLASS (NOT A SQLALCHEMY MODEL):
This object lives entirely in application memory. It is the OUTPUT of a
scoring strategy and the INPUT to whatever persists, displays, or acts on
the score later. By keeping it free of database dependencies, we can test
scoring logic without a database and swap persistence strategies without
changing the score itself.

The ``contributing_factors`` dict is the receipt for every score this system
produces. If it is ever empty or full of ``None`` values, that means the
upstream data pipeline is broken -- not a normal state, and not a design
choice.
"""

from dataclasses import dataclass
from datetime import datetime

from app.health_risk.domain.disease_category import DiseaseCategory


@dataclass
class RiskScore:
    """
    A fully-traced risk score for one disease in one location at one time.

    Fields:
        pincode:            The postal code this score applies to.
        disease_category:   Which disease this score is for (DENGUE, LEPTOSPIROSIS, VIRAL_FEVER).
        score:              Numeric risk value from 0.0 (no risk) to 100.0 (maximum risk).
                            This scale deliberately matches the existing ``trend_score`` 0-100
                            scale so that the procurement threshold logic in
                            ``procurement_router.py`` (``if trend_score > 70.0``) continues
                            to work without silent breakage.
        confidence:         One of "real_data" (all inputs fresh), "fallback_neutral"
                            (missing data, returned middle value), or "stale_cache"
                            (used cached inputs older than threshold).
        computed_at:        Timestamp of when this score was calculated.
        contributing_factors:  Dict of raw inputs that produced this score, e.g.
                            ``{"trend_score": 82.0, "humidity_percent": 91.0, "rain_mm": 12.0}``.
    """

    pincode: str
    disease_category: DiseaseCategory
    score: float
    confidence: str
    computed_at: datetime
    contributing_factors: dict

    def __post_init__(self) -> None:
        """
        Validate the score is within the 0.0-100.0 range.

        WHY THIS VALIDATION EXISTS:
        The existing procurement router checks ``trend_score > 70.0`` to decide
        whether to trigger a disease-wave alert. If a score somehow escapes this
        range (e.g. a bug feeds in a raw probability like 0.89 instead of 89.0),
        the threshold comparison would either never fire or always fire -- silently
        breaking the alert system. We catch it here, at the point of creation,
        rather than debugging it in production.
        """
        if not (0.0 <= self.score <= 100.0):
            raise ValueError(
                f"RiskScore score must be between 0.0 and 100.0, got {self.score}. "
                "This range matches the existing trend_score 0-100 scale used by "
                "the procurement router threshold checks."
            )
