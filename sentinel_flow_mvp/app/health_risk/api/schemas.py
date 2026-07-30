"""
Pydantic response schemas for the health_risk REST API.

WHY SEPARATE FROM THE DOMAIN:
The domain RiskScore dataclass (in domain/risk_score.py) carries a
contributing_factors dict and a DiseaseCategory enum — internal details
that should never leak to the API layer. These Pydantic models are the
contract between the API and its consumers: they define exactly what JSON
shape the frontend can rely on. Any change here is a breaking change.
"""

from datetime import datetime
from typing import List

from pydantic import BaseModel


class HealthRiskScoreResponse(BaseModel):
    """
    What the API sends back for one disease's current risk score.

    Matches the HealthRiskScoreModel columns that are safe to expose:
    disease_category (string), score (float 0-100), confidence level,
    and when it was computed. No internal IDs or contributing_factors.
    """

    disease_category: str
    score: float
    confidence: str
    computed_at: datetime


class HealthRiskCurrentResponse(BaseModel):
    """
    The full response for a pharmacy's current risk snapshot,
    covering all disease categories.

    pincode identifies the location. scores is a list of the most recent
    score per disease category — there is at most one entry per disease.
    """

    pincode: str
    scores: List[HealthRiskScoreResponse]
