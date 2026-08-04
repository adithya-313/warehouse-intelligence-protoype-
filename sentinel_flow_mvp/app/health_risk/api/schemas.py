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
    id (for /explain deep links), disease_category (string), score
    (float 0-100), confidence level, and when it was computed. No
    contributing_factors.
    """

    # Lets the frontend call /explain/{id} without a second lookup.
    id: int
    disease_category: str
    score: float
    confidence: str
    computed_at: datetime


class HealthRiskCurrentScoreResponse(BaseModel):
    """
    One disease's current risk score plus a data_status signal for
    /current ONLY.

    We deliberately do NOT reuse HealthRiskScoreResponse here: the
    /current endpoint is the only one that answers "is my snapshot
    reliable right now?", so it is the only endpoint carrying
    data_status. HealthRiskScoreResponse stays untouched for /history
    and /explain, which answer different questions and should not
    suddenly grow a field consumers did not ask for.

    data_status meaning:
      - "real_data" — the majority of the last 3 ingestion runs for
        this disease used genuinely useful inputs (trend/weather),
        so the current score is trustworthy.
      - "degraded"   — the majority of the last 3 runs were TOTAL
        fallbacks (no trend, no humidity, no rain at all). The score
        is still returned (never hide data), but consumers know the
        evidence base has gone quiet.

    A "weather-only" fallback (trend missing but humidity/rain present)
    counts as real data, NOT degraded — weather is still a genuine
    measurement even when search-trend data is unavailable.

    risk_tier is the server-side severity band ("Low"/"Moderate"/"High"/
    "Severe") computed from the score — /current only, like data_status.
    """

    # Lets the frontend call /explain/{id} without a second lookup.
    id: int
    disease_category: str
    score: float
    confidence: str
    computed_at: datetime
    # Server-side severity band — computed from the score, never on the client.
    risk_tier: str
    data_status: str


class HealthRiskCurrentResponse(BaseModel):
    """
    The full response for a pharmacy's current risk snapshot,
    covering all disease categories.

    pincode identifies the location. scores is a list of the most recent
    score per disease category — there is at most one entry per disease.
    """

    pincode: str
    scores: List[HealthRiskCurrentScoreResponse]


class HealthRiskHistoryResponse(BaseModel):
    """
    The full history of risk scores for a pharmacy over the requested
    number of days, across all disease categories.
    """

    pincode: str
    days: int
    scores: List[HealthRiskScoreResponse]


class HealthRiskExplainResponse(BaseModel):
    """
    The full signal breakdown behind one specific risk score —
    shows exactly which raw inputs (trend data, weather data) fed into
    this number, so a pharmacist can see the reasoning, not just trust
    a bare number.
    """

    id: int
    pincode: str
    disease_category: str
    score: float
    confidence: str
    computed_at: datetime
    contributing_factors: dict
