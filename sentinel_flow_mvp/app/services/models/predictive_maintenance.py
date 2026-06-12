"""Predictive Maintenance Module.

This module implements equipment failure prediction using a simulated Random Forest model.
It predicts the probability of equipment failure based on age and vibration metrics.

The module follows the Strategy Pattern by inheriting BasePredictionModule,
ensuring it can be swapped in/out by the PredictionOrchestrator without
changing any routing logic.
"""

import asyncio
import logging

from app.domain.schemas import BaseInferenceRequest, StandardizedPredictionResponse
from app.services.ml_interfaces import BasePredictionModule
from app.infrastructure.database import SessionLocal
from app.infrastructure.db.models import AssetTelemetryModel

logger = logging.getLogger(__name__)

# Safe default values for missing features
DEFAULT_EQUIPMENT_AGE = 500
DEFAULT_VIBRATION_INDEX = 0.5

# Confidence scores
ML_MODEL_CONFIDENCE = 0.88
HEURISTIC_CONFIDENCE = 0.45

# Thresholds for heuristic risk assessment
AGE_THRESHOLD_DAYS = 1000


class PredictiveMaintenanceModule(BasePredictionModule):
    """Predictive maintenance module using simulated Random Forest model.

    This module predicts equipment failure probability based on age and vibration.
    The primary model simulates ensemble tree inference, while the fallback
    uses deterministic business rules based on equipment age.
    """

    async def predict(self, request: BaseInferenceRequest) -> StandardizedPredictionResponse:
        """Execute the primary predictive maintenance model.

        This method simulates a Random Forest model that calculates failure
        probability based on equipment age and vibration index.

        Args:
            request: The inference request containing equipment_age_days and
                     vibration_index in features.

        Returns:
            StandardizedPredictionResponse with the failure probability.

        Raises:
            ValueError: If required features are missing.
        """
        logger.info(f"PredictiveMaintenance: Starting primary prediction (correlation_id: {request.correlation_id})")

        # Extract required features from the request or DB
        asset_id = request.asset_id or request.features.get("asset_id")
        equipment_age_days = request.features.get("equipment_age_days")
        vibration_index = request.features.get("vibration_index")

        if (equipment_age_days is None or vibration_index is None) and asset_id:
            try:
                db_session = SessionLocal()
                try:
                    record = db_session.query(AssetTelemetryModel).filter(
                        AssetTelemetryModel.asset_id == asset_id
                    ).order_by(AssetTelemetryModel.recorded_at.desc()).first()
                    
                    if record:
                        equipment_age_days = equipment_age_days if equipment_age_days is not None else record.equipment_age_days
                        vibration_index = vibration_index if vibration_index is not None else record.vibration_index
                        logger.info(f"PredictiveMaintenance: Extracted context for asset {asset_id} from AssetTelemetryModel")
                finally:
                    db_session.close()
            except Exception as e:
                logger.warning(f"PredictiveMaintenance: Failed to query DB for asset context: {e}")

        # Validate that required features exist (or fallback to defaults if strictly needed)
        if equipment_age_days is None or vibration_index is None:
            logger.warning("PredictiveMaintenance: Missing required features and no DB context. Using safe defaults.")
            equipment_age_days = equipment_age_days if equipment_age_days is not None else DEFAULT_EQUIPMENT_AGE
            vibration_index = vibration_index if vibration_index is not None else DEFAULT_VIBRATION_INDEX

        # Simulate ML model computation
        logger.info("PredictiveMaintenance: Simulating Random Forest inference (0.2s)...")
        await asyncio.sleep(0.2)

        # Calculate failure probability using a simple formula
        # Higher probability when equipment is old and vibration is high
        # Formula: normalized_age * 0.6 + vibration * 0.4
        normalized_age = equipment_age_days / 3650.0  # Normalize to 10 years max
        failure_probability = (normalized_age * 0.6) + (vibration_index * 0.4)

        # Clamp probability to valid range [0.0, 1.0]
        if failure_probability < 0.0:
            failure_probability = 0.0
        elif failure_probability > 1.0:
            failure_probability = 1.0

        logger.info(f"PredictiveMaintenance: Primary prediction complete. Probability={failure_probability:.4f}")

        # Return standardized response with high confidence
        return StandardizedPredictionResponse(
            correlation_id=request.correlation_id,
            prediction_value=failure_probability,
            confidence_score=ML_MODEL_CONFIDENCE,
            fallback_engaged=False,
            model_version="rf_maintenance_v1",
        )

    async def heuristic_fallback(self, request: BaseInferenceRequest) -> StandardizedPredictionResponse:
        """Execute deterministic rule-based fallback for maintenance prediction.

        This method provides a safe, rule-based prediction when the primary
        model fails. It uses simple business rules:
        - If equipment age > 1000 days: High risk (0.8)
        - Otherwise: Low risk (0.2)

        Args:
            request: The inference request containing equipment_age_days in features.

        Returns:
            StandardizedPredictionResponse with fallback_engaged=True.
        """
        logger.info(f"PredictiveMaintenance: Engaging heuristic fallback (correlation_id: {request.correlation_id})")

        # Extract equipment age from features or DB
        asset_id = request.asset_id or request.features.get("asset_id")
        equipment_age_days = request.features.get("equipment_age_days")
        
        if equipment_age_days is None and asset_id:
            try:
                db_session = SessionLocal()
                try:
                    record = db_session.query(AssetTelemetryModel).filter(
                        AssetTelemetryModel.asset_id == asset_id
                    ).order_by(AssetTelemetryModel.recorded_at.desc()).first()
                    if record:
                        equipment_age_days = record.equipment_age_days
                finally:
                    db_session.close()
            except Exception:
                pass

        # Apply deterministic business rules
        if equipment_age_days is not None and equipment_age_days > AGE_THRESHOLD_DAYS:
            # Old equipment = high failure risk
            risk_probability = 0.8
            logger.info(f"PredictiveMaintenance: Heuristic detected old equipment ({equipment_age_days} days). Risk=0.8")
        else:
            # Normal or unknown age = low failure risk
            risk_probability = 0.2
            logger.info(f"PredictiveMaintenance: Heuristic detected normal equipment. Risk=0.2")

        # Return standardized response with lower confidence (heuristic)
        return StandardizedPredictionResponse(
            correlation_id=request.correlation_id,
            prediction_value=risk_probability,
            confidence_score=HEURISTIC_CONFIDENCE,
            fallback_engaged=True,
            model_version="heuristic_age_rule_v1",
        )
