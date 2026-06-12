"""Federated Learning Ingress API Routes.

This module exposes endpoints for the hub-and-spoke federated architecture.
Supplier edge nodes submit local model weights, which are then aggregated
by the SGWA (Supply-Graph Weighted Aggregation) mathematical defence layer.

Domain-Driven Design context:
- /weights/aggregate is the central aggregation endpoint.
- Each edge node sends a FederatedWeightPayload; the service applies a
  Trimmed Mean filter to exclude poisoned or anomalous updates.
"""

import logging
from typing import List

from fastapi import APIRouter, HTTPException, status

from app.domain.schemas import FederatedWeightPayload
from app.services.sgwa_service import SGWAService

logger = logging.getLogger(__name__)

router: APIRouter = APIRouter()

sgwa_service: SGWAService = SGWAService()


@router.post(
    path="/weights/aggregate",
    status_code=status.HTTP_200_OK,
    summary="Aggregate federated weight updates via Trimmed Mean",
    description="Accepts a list of FederatedWeightPayloads from supplier "
    "edge nodes, applies a Trimmed Mean defence to filter poisoned "
    "updates, and returns the aggregated weight vector.",
)
def aggregate_weights_endpoint(
    weight_payloads: List[FederatedWeightPayload],
) -> dict:
    """Aggregate supplier weight updates with poisoned-update rejection.

    Args:
        weight_payloads: List of validated weight payloads from edge nodes.

    Returns:
        A dictionary containing the aggregated weight vector.

    Raises:
        HTTPException 400: If the SGWA service rejects the payloads
                           (e.g., empty list or all nodes flagged).
    """
    logger.info(
        f"Weight aggregation requested: {len(weight_payloads)} suppliers."
    )

    try:
        aggregated_weights = sgwa_service.aggregate_weights(
            weight_payloads=weight_payloads,
        )

        logger.info(
            f"Aggregation successful: {len(aggregated_weights)} weights."
        )

        return {
            "status": "success",
            "aggregated_weights": aggregated_weights,
            "suppliers_contributing": len(weight_payloads),
        }

    except ValueError as validation_error:
        logger.warning(
            f"Weight aggregation rejected: {str(validation_error)}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "aggregation_failed",
                "message": str(validation_error),
            },
        )
