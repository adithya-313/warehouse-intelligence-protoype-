"""Background Worker Tasks.

Executes asynchronous jobs, fetches ML predictions, validates them via Aegis, and writes to the database.
"""

import logging
import uuid
from typing import Any, Dict

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.celery_app import celery_application
from app.infrastructure.database import SessionLocal
from app.infrastructure.models import MLPredictionLog, SupplierModel, TelemetryModel
from app.services.aegis_service import validate_and_enforce_prediction_schema
from app.services.drift_service import detect_stockout_drift
from app.services.lora_training_worker import train_lora_adapter
from app.services.ml_service import generate_mock_stockout_prediction

from app.core.logging import configure_logging
configure_logging(level=logging.INFO, json_output=True)
logger = logging.getLogger(__name__)


@celery_application.task(name="process_telemetry_batch")
def process_batch_payload_task(
    payload_dictionary: Dict[str, Any],
    tracking_job_id: str,
) -> str:
    """Iterates through the batch, requests AI predictions, validates with Aegis, and persists data.

    Args:
        payload_dictionary: The raw dictionary representation of the IngestionPayload.
        tracking_job_id: The unique ID returned to the client for tracking.

    Returns:
        Success message indicating the number of records processed.
    """
    logger.info(f"Starting execution for job ID: {tracking_job_id}")
    database_session: Session = SessionLocal()

    try:
        source_system_origin = payload_dictionary.get("source_system", "UNKNOWN")
        record_list = payload_dictionary.get("records", [])

        for record_data in record_list:
            supplier_id_string = record_data.get("supplier_id")
            inventory_level = record_data.get("inventory_count")
            delay_days = record_data.get("delivery_delay_days")

            # Generate a unique tracking ID for this specific prediction
            prediction_tracking_id = str(uuid.uuid4())

            supplier_entity = SupplierModel(
                supplier_id=supplier_id_string,
                system_origin=source_system_origin,
                industry_vertical="GENERAL",
                industry_specific_metadata={},
            )
            database_session.merge(supplier_entity)

            raw_ml_prediction = generate_mock_stockout_prediction(
                supplier_id_string=supplier_id_string,
                current_inventory=inventory_level,
                delivery_delay=delay_days,
            )

            # Add tracking_id to the raw prediction for Aegis validation
            raw_ml_prediction["tracking_id"] = prediction_tracking_id

            validated_prediction = validate_and_enforce_prediction_schema(
                raw_prediction_data=raw_ml_prediction,
            )

            # Insert the prediction into the ML prediction log
            prediction_log_entity = MLPredictionLog(
                tracking_id=prediction_tracking_id,
                predicted_stockout_probability=validated_prediction.predicted_stockout_probability,
            )
            database_session.add(prediction_log_entity)

            # Insert telemetry with the tracking_id link
            telemetry_entity = TelemetryModel(
                recorded_at=record_data.get("timestamp"),
                supplier_id=supplier_id_string,
                tracking_id=prediction_tracking_id,
                inventory_count=inventory_level,
                delivery_delay_days=delay_days,
                predicted_stockout_probability=validated_prediction.predicted_stockout_probability,
                is_critical_risk=validated_prediction.is_critical_risk,
            )
            database_session.add(telemetry_entity)

        database_session.commit()
        success_message = f"Job {tracking_job_id} successfully processed and validated {len(record_list)} records."
        logger.info(success_message)
        return success_message

    except Exception as execution_error:
        database_session.rollback()
        logger.error(f"Failure in job {tracking_job_id}: {str(execution_error)}")
        raise

    finally:
        database_session.close()


@celery_application.task(name="run_drift_analysis")
def run_drift_analysis_task() -> str:
    """Periodic task that calculates PSI and detects model drift.

    This task is scheduled to run every 5 minutes via Celery Beat.
    It queries the database for recent predictions and actuals,
    calculates the Population Stability Index, and updates Prometheus metrics.

    Returns:
        A status message indicating the drift analysis result.
    """
    logger.info("Starting periodic drift analysis task")
    database_session: Session = SessionLocal()

    try:
        # Call the drift detection service.
        # NOTE: detect_stockout_drift() returns a Dict[str, float], not a bare float.
        # The dict always contains a 'psi' key. We extract it before any comparison.
        psi_result = detect_stockout_drift(database_session=database_session)
        psi_value: float = psi_result["psi"]

        # Step 2: Check if critical drift was detected (PSI > 0.2)
        # If so, trigger asynchronous LoRA fine-tuning to adapt the model
        # The training uses the last 24 hours of data to create a new adapter
        PSI_CRITICAL_THRESHOLD = 0.2

        if psi_value > PSI_CRITICAL_THRESHOLD:
            logger.warning(
                f"Critical drift detected: PSI={psi_value:.4f} exceeds {PSI_CRITICAL_THRESHOLD}. "
                f"Triggering LoRA fine-tuning for module 'stockout_prediction'."
            )

            # Trigger asynchronous LoRA training via Celery
            # The worker will simulate fetching 24 hours of training data
            # and create a new LoRA adapter for the stockout_prediction module
            train_lora_adapter.delay(
                module_name="stockout_prediction",
                training_data_window_hours=24,
            )

            logger.info("LoRA fine-tuning task dispatched to Celery worker.")

        result_message = f"Drift analysis complete. PSI={psi_value:.4f}"
        logger.info(result_message)
        return result_message

    except Exception as execution_error:
        database_session.rollback()
        logger.error(f"Drift analysis failed: {str(execution_error)}")
        raise

    finally:
        database_session.close()

@celery_application.task(name="predict_forecast", bind=True)
def predict_forecast_task(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
    from app.main import prediction_orchestrator, app as fast_app
    from chronos import ChronosPipeline
    from app.domain.schemas import BaseInferenceRequest
    import torch
    import asyncio
    
    # Ensure chronos pipeline is loaded in this Celery worker process
    if getattr(fast_app.state, "chronos_pipeline", None) is None:
        logger.info("Initializing Chronos base model for Celery Worker...")
        fast_app.state.chronos_pipeline = ChronosPipeline.from_pretrained(
            "amazon/chronos-t5-mini",
            device_map="cuda" if torch.cuda.is_available() else "cpu",
            torch_dtype=torch.float32
        )
        # Register modules in orchestrator inside worker
        if not prediction_orchestrator._module_registry:
            from app.services.models.demand_forecast import DemandForecastingModule
            from app.services.models.stockout_prediction import StockoutPredictionModule
            prediction_orchestrator.register_module("demand_forecast", DemandForecastingModule())
            prediction_orchestrator.register_module("stockout_prediction", StockoutPredictionModule())

    request = BaseInferenceRequest(**request_data)
    
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    result = loop.run_until_complete(
        prediction_orchestrator.execute_prediction(request=request)
    )
    
    return result.model_dump()
