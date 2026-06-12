"""Fuel Cost Estimation Module.

This module implements fuel cost prediction using a simulated XGBoost model.
It estimates fuel costs based on route distance and vehicle efficiency.

The module follows the Strategy Pattern by inheriting BasePredictionModule,
ensuring it can be swapped in/out by the PredictionOrchestrator without
changing any routing logic.
"""

import asyncio
import logging

from app.domain.schemas import BaseInferenceRequest, StandardizedPredictionResponse
from app.services.ml_interfaces import BasePredictionModule
from app.infrastructure.database import SessionLocal
from app.infrastructure.db.models import RouteTelemetryModel

logger = logging.getLogger(__name__)

# Safe default values for missing features
DEFAULT_DISTANCE_KM = 100.0
DEFAULT_EFFICIENCY = 10.0

# Confidence scores
ML_MODEL_CONFIDENCE = 0.92
HEURISTIC_CONFIDENCE = 0.50

# Flat rate per km for heuristic fallback
FLAT_RATE_PER_KM = 0.5


class FuelCostModule(BasePredictionModule):
    """Fuel cost estimation module using simulated XGBoost model.

    This module predicts fuel costs based on route distance and vehicle efficiency.
    The primary model simulates gradient boosting regression, while the fallback
    uses a simple flat-rate calculation.
    """

    async def predict(self, request: BaseInferenceRequest) -> StandardizedPredictionResponse:
        """Execute the primary fuel cost estimation model.

        This method simulates an XGBoost model that calculates fuel cost
        based on distance and efficiency.

        Args:
            request: The inference request containing route_distance_km and
                     vehicle_efficiency in features.

        Returns:
            StandardizedPredictionResponse with the estimated cost in USD.

        Raises:
            ValueError: If required features are missing.
        """
        logger.info(f"FuelCost: Starting primary prediction (correlation_id: {request.correlation_id})")

        # Extract required features from the request or DB
        route_id = request.route_id or request.features.get("route_id")
        route_distance_km = request.features.get("route_distance_km")
        vehicle_efficiency = request.features.get("vehicle_efficiency")

        if (route_distance_km is None or vehicle_efficiency is None) and route_id:
            try:
                db_session = SessionLocal()
                try:
                    record = db_session.query(RouteTelemetryModel).filter(
                        RouteTelemetryModel.route_id == route_id
                    ).order_by(RouteTelemetryModel.recorded_at.desc()).first()
                    
                    if record:
                        route_distance_km = route_distance_km if route_distance_km is not None else record.route_distance_km
                        vehicle_efficiency = vehicle_efficiency if vehicle_efficiency is not None else record.vehicle_efficiency
                        logger.info(f"FuelCost: Extracted context for route {route_id} from RouteTelemetryModel")
                finally:
                    db_session.close()
            except Exception as e:
                logger.warning(f"FuelCost: Failed to query DB for route context: {e}")

        # Validate that required features exist (or fallback to defaults)
        if route_distance_km is None or vehicle_efficiency is None:
            logger.warning("FuelCost: Missing required features and no DB context. Using safe defaults.")
            route_distance_km = route_distance_km if route_distance_km is not None else DEFAULT_DISTANCE_KM
            vehicle_efficiency = vehicle_efficiency if vehicle_efficiency is not None else DEFAULT_EFFICIENCY

        # Simulate ML model computation
        logger.info("FuelCost: Simulating XGBoost inference (0.1s)...")
        await asyncio.sleep(0.1)

        # Calculate estimated fuel cost
        # Formula: (distance / efficiency) * fuel_price_factor
        # Assume fuel price factor of 1.5 USD per liter/gallon equivalent
        fuel_price_factor = 1.5
        estimated_cost = (route_distance_km / vehicle_efficiency) * fuel_price_factor

        logger.info(f"FuelCost: Primary prediction complete. Cost=${estimated_cost:.2f}")

        # Return standardized response with high confidence
        return StandardizedPredictionResponse(
            correlation_id=request.correlation_id,
            prediction_value=estimated_cost,
            confidence_score=ML_MODEL_CONFIDENCE,
            fallback_engaged=False,
            model_version="xgb_fuel_v2",
        )

    async def heuristic_fallback(self, request: BaseInferenceRequest) -> StandardizedPredictionResponse:
        """Execute deterministic flat-rate fallback for fuel cost estimation.

        This method provides a safe, rule-based prediction when the primary
        model fails. It uses a simple flat rate per kilometer.

        Args:
            request: The inference request containing route_distance_km in features.

        Returns:
            StandardizedPredictionResponse with fallback_engaged=True.
        """
        logger.info(f"FuelCost: Engaging heuristic fallback (correlation_id: {request.correlation_id})")

        # Extract route distance from features or DB
        route_id = request.route_id or request.features.get("route_id")
        route_distance_km = request.features.get("route_distance_km")
        
        if route_distance_km is None and route_id:
            try:
                db_session = SessionLocal()
                try:
                    record = db_session.query(RouteTelemetryModel).filter(
                        RouteTelemetryModel.route_id == route_id
                    ).order_by(RouteTelemetryModel.recorded_at.desc()).first()
                    if record:
                        route_distance_km = record.route_distance_km
                finally:
                    db_session.close()
            except Exception:
                pass

        # Apply deterministic flat rate calculation
        if route_distance_km is not None:
            estimated_cost = route_distance_km * FLAT_RATE_PER_KM
            logger.info(f"FuelCost: Heuristic calculated cost: ${estimated_cost:.2f} ({route_distance_km} km * ${FLAT_RATE_PER_KM}/km)")
        else:
            # No distance provided - use safe default
            estimated_cost = DEFAULT_DISTANCE_KM * FLAT_RATE_PER_KM
            logger.info(f"FuelCost: No distance provided. Using default: ${estimated_cost:.2f}")

        # Return standardized response with lower confidence (heuristic)
        return StandardizedPredictionResponse(
            correlation_id=request.correlation_id,
            prediction_value=estimated_cost,
            confidence_score=HEURISTIC_CONFIDENCE,
            fallback_engaged=True,
            model_version="heuristic_flat_rate_v1",
        )
