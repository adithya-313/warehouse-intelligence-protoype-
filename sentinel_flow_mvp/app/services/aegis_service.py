"""Aegis Lite Circuit Breaker Service.

Intercepts raw ML outputs and enforces strict mathematical and compliance schemas.
"""

import logging

from pydantic import ValidationError

from app.domain.schemas import PredictionResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def validate_and_enforce_prediction_schema(
    raw_prediction_data: dict,
) -> PredictionResponse:
    """Forces raw ML inference data through the strict PredictionResponse Pydantic contract.

    Args:
        raw_prediction_data: The unvalidated output from the ML service.

    Returns:
        A strictly typed, mathematically validated object.

    Raises:
        ValueError: If the AI output violates the Pydantic schema or regional compliance rules.
    """
    try:
        validated_prediction_object = PredictionResponse(**raw_prediction_data)

        allowed_regions = ["INDIA_DPDP", "EU_GDPR", "DEFAULT"]
        if validated_prediction_object.compliance_region not in allowed_regions:
            raise ValueError(
                f"Aegis Blocked: Invalid compliance jurisdiction '{validated_prediction_object.compliance_region}'"
            )

        return validated_prediction_object

    except ValidationError as schema_error:
        logger.error(f"Aegis Validation Failed. AI Output rejected: {str(schema_error)}")
        raise ValueError("AI prediction output violated strict schema constraints.")