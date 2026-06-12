"""Stockout Prediction Module.

This module predicts stockout risk using the shared Chronos-T5 base model
with optional supplier-specific LoRA adapters. It forecasts inventory depletion
over a 5‑step horizon and computes the probability of running out of stock.

The module follows the Strategy Pattern by inheriting BasePredictionModule.
"""

import asyncio
import hashlib
import logging
import os
import time

import numpy as np
import torch

from app.domain.schemas import BaseInferenceRequest, StandardizedPredictionResponse
from app.services.ml_interfaces import BasePredictionModule
from app.services.models import adapter_lock
from app.infrastructure.database import SessionLocal
from app.infrastructure.models import TelemetryModel
from app.infrastructure.db.models import LoRAAdapterRegistry

logger = logging.getLogger(__name__)

DEFAULT_INVENTORY = 50
DEFAULT_LEAD_TIME = 7

ML_LORA_CONFIDENCE = 0.85
ML_BASE_CONFIDENCE = 0.70
HEURISTIC_CONFIDENCE = 0.50

LOW_INVENTORY_THRESHOLD = 10


class StockoutPredictionModule(BasePredictionModule):
    """Stockout risk prediction module using Chronos-T5 with dynamic LoRA adapters.

    The module accesses the shared ChronosPipeline via app.state,
    hot-swaps supplier LoRA adapters under the shared adapter_lock,
    forecasts inventory depletion over a 5‑step horizon, and computes
    the probability of a stockout event within the lead-time window.
    """

    async def predict(self, request: BaseInferenceRequest) -> StandardizedPredictionResponse:
        logger.info(f"StockoutPrediction: Starting primary prediction (correlation_id: {request.correlation_id})")

        supplier_id = request.supplier_id or request.features.get("supplier_id") or request.client_id
        if not supplier_id or supplier_id == "anonymous":
            raise ValueError("StockoutPrediction: supplier_id is missing and required for Chronos inference")

        sku_id = request.sku_id or request.features.get("sku_id")
        current_inventory = request.features.get("current_inventory")
        lead_time_days = request.features.get("lead_time_days", DEFAULT_LEAD_TIME)

        # ------------------------------------------------------------------
        # Access the globally loaded ChronosPipeline from FastAPI app state
        # ------------------------------------------------------------------
        try:
            from app.main import app
            pipeline = getattr(app.state, "chronos_pipeline", None)
            if pipeline is None:
                raise RuntimeError("ChronosPipeline is not initialized in app.state")
        except ImportError:
            raise RuntimeError("Could not import app.main.app to access global pipeline")

        db_session = SessionLocal()
        adapter_used = False
        forecast_trajectory: list[float] = []
        historical_trajectory: list[float] = []
        swap_in_latency_ms = 0.0
        compute_latency_ms = 0.0
        swap_out_latency_ms = 0.0

        try:
            # Query for the latest ACTIVE adapter for this supplier
            adapter_record = db_session.query(LoRAAdapterRegistry).filter(
                LoRAAdapterRegistry.module_name == "stockout_prediction",
                LoRAAdapterRegistry.supplier_id == supplier_id,
                LoRAAdapterRegistry.status == "ACTIVE",
            ).order_by(LoRAAdapterRegistry.created_at.desc()).first()

            # Fetch up to 90 days of telemetry for the Chronos context window
            query = db_session.query(TelemetryModel).filter(
                TelemetryModel.supplier_id == supplier_id,
            )
            if sku_id:
                query = query.filter(TelemetryModel.sku_id == sku_id)

            records = query.order_by(TelemetryModel.recorded_at.desc()).limit(90).all()

            if records:
                records.reverse()
                historical_trajectory = [float(r.inventory_count) for r in records]
                if current_inventory is None:
                    current_inventory = historical_trajectory[-1]
                if lead_time_days is None:
                    lead_time_days = records[-1].delivery_delay_days or DEFAULT_LEAD_TIME

                # Build Chronos context tensor: strictly (1, 90)
                inventory_data = list(historical_trajectory)
                if len(inventory_data) < 90:
                    padding = [inventory_data[0]] * (90 - len(inventory_data))
                    inventory_data = padding + inventory_data
                elif len(inventory_data) > 90:
                    inventory_data = inventory_data[-90:]
                logger.info(f"StockoutPrediction: DB data extracted. Length: {len(historical_trajectory)}")
                with open("/tmp/stockout_debug.txt", "a") as f:
                    f.write(f"DB data extracted. Length: {len(historical_trajectory)}, supplier_id: {supplier_id}, sku_id: {sku_id}\n")
            else:
                # No telemetry available; repeat current_inventory 90 times
                logger.warning(f"StockoutPrediction: No telemetry records for supplier={supplier_id}, sku={sku_id}; using current_inventory as static context.")
                with open("/tmp/stockout_debug.txt", "a") as f:
                    f.write(f"No telemetry records for supplier={supplier_id}, sku_id={sku_id}\n")
                if current_inventory is None:
                    current_inventory = DEFAULT_INVENTORY
                inventory_data = [float(current_inventory)] * 90

            context_tensor = torch.tensor(inventory_data, dtype=torch.float32).view(1, 90)

            # ------------------------------------------------------------------
            # Acquire the shared adapter lock to hot-swap the LoRA adapter
            # safely, run Chronos inference, and clean up the adapter before
            # releasing the lock.  The same lock is used by demand_forecast.py
            # so adapter state is never corrupted by concurrent requests.
            # ------------------------------------------------------------------
            async with adapter_lock:
                if adapter_record and adapter_record.adapter_weights_path:
                    safetensors_path = os.path.join(
                        adapter_record.adapter_weights_path, "adapter_model.safetensors"
                    )
                    if not os.path.exists(safetensors_path):
                        logger.warning(
                            "StockoutPrediction: Adapter safetensors missing at %s. Skipping.",
                            safetensors_path,
                        )
                    else:
                        sha256_hash = hashlib.sha256()
                        with open(safetensors_path, "rb") as f:
                            for byte_block in iter(lambda: f.read(4096), b""):
                                sha256_hash.update(byte_block)
                        computed_checksum = sha256_hash.hexdigest()
                        if adapter_record.checksum and computed_checksum != adapter_record.checksum:
                            logger.critical(
                                "StockoutPrediction: Checksum mismatch for adapter %s. Aborting.",
                                adapter_record.id,
                            )
                            raise ValueError("Adapter checksum mismatch")

                        logger.info(
                            "StockoutPrediction: Loading LoRA adapter for %s from %s",
                            supplier_id, adapter_record.adapter_weights_path,
                        )
                        t0_swap_in = time.perf_counter()
                        pipeline.model.load_adapter(
                            adapter_record.adapter_weights_path, adapter_name="stockout_lora"
                        )
                        pipeline.model.set_adapter("stockout_lora")
                        swap_in_latency_ms = (time.perf_counter() - t0_swap_in) * 1000.0
                        adapter_used = True

                if not adapter_used:
                    logger.info(
                        "StockoutPrediction: No ACTIVE adapter for %s. Using zero-shot Chronos base model.",
                        supplier_id,
                    )
                    try:
                        pipeline.model.disable_adapters()
                    except Exception:
                        pass

                try:
                    t0_compute = time.perf_counter()
                    forecast = await asyncio.to_thread(
                        pipeline.predict, context_tensor, prediction_length=5
                    )
                    compute_latency_ms = (time.perf_counter() - t0_compute) * 1000.0

                    if isinstance(forecast[0], torch.Tensor):
                        try:
                            forecast_trajectory = forecast[0].median(dim=0).values.tolist()
                        except Exception:
                            forecast_trajectory = forecast[0].mean(dim=0).tolist()
                    else:
                        try:
                            forecast_trajectory = np.median(forecast[0], axis=0).tolist()
                        except Exception:
                            forecast_trajectory = np.mean(forecast[0], axis=0).tolist()

                    forecast_trajectory = [float(x) for x in forecast_trajectory]

                finally:
                    if adapter_used:
                        t0_swap_out = time.perf_counter()
                        try:
                            pipeline.model.delete_adapter("stockout_lora")
                        except Exception as e:
                            logger.warning(
                                "StockoutPrediction: Failed to delete adapter 'stockout_lora': %s", e
                            )
                        try:
                            pipeline.model.disable_adapters()
                        except Exception:
                            pass
                        swap_out_latency_ms = (time.perf_counter() - t0_swap_out) * 1000.0

        except torch.cuda.OutOfMemoryError as oom_error:
            logger.error("StockoutPrediction OOM: %s. Clearing CUDA cache.", oom_error)
            torch.cuda.empty_cache()
            raise
        except Exception as execution_error:
            logger.error("StockoutPrediction execution failed: %s", execution_error)
            raise
        finally:
            db_session.close()

        # ------------------------------------------------------------------
        # Deterministic depletion loop
        #   Inventory_t = current_inventory - sum_{i=1}^{t} PredictedDemand_i
        # If Inventory_t <= 0, stockout_detected = True
        # ------------------------------------------------------------------
        remaining = float(current_inventory)
        depletion_trajectory: list[float] = []
        stockout_detected = False
        days_until_depletion = -1

        for i, demand in enumerate(forecast_trajectory):
            remaining -= max(0.0, demand)
            depletion_trajectory.append(max(0.0, remaining))
            if not stockout_detected and remaining <= 0:
                stockout_detected = True
                days_until_depletion = i + 1

        # Compute stockout probability
        lead = max(lead_time_days, 1)
        if stockout_detected:
            stockout_probability = max(0.0, min(1.0, days_until_depletion / lead))
        elif remaining <= 0:
            stockout_probability = 1.0
        else:
            stockout_probability = max(0.0, min(1.0, 1.0 - (remaining / max(float(current_inventory), 1.0))))

        logger.info(
            "StockoutPrediction: Complete. probability=%.4f, stockout_detected=%s, days=%d",
            stockout_probability, stockout_detected, days_until_depletion,
        )

        response = StandardizedPredictionResponse(
            correlation_id=request.correlation_id,
            prediction_value=stockout_probability,
            confidence_score=ML_LORA_CONFIDENCE if adapter_used else ML_BASE_CONFIDENCE,
            fallback_engaged=False,
            model_version="chronos_lora_stockout_v1" if adapter_used else "chronos_base_stockout_v1",
            historical_trajectory=historical_trajectory,
            forecast_trajectory=forecast_trajectory,
            execution_metadata={
                "stockout_detected": stockout_detected,
                "days_until_depletion": days_until_depletion,
                "inventory_depletion_curve": depletion_trajectory,
                "swap_in_latency_ms": swap_in_latency_ms,
                "compute_latency_ms": compute_latency_ms,
                "swap_out_latency_ms": swap_out_latency_ms,
            },
        )

        return response

    async def heuristic_fallback(self, request: BaseInferenceRequest) -> StandardizedPredictionResponse:
        """Execute deterministic rule-based fallback for stockout prediction.

        Provides a safe, rule-based prediction when the primary Chronos model fails.
        Uses simple business rules:
        - If inventory < 10: High risk (0.9)
        - Otherwise: Low risk (0.1)
        """
        logger.info(f"StockoutPrediction: Engaging heuristic fallback (correlation_id: {request.correlation_id})")

        supplier_id = request.supplier_id or request.features.get("supplier_id") or request.client_id
        sku_id = request.sku_id or request.features.get("sku_id")
        current_inventory = request.features.get("current_inventory")

        historical_trajectory: list[float] = []

        if current_inventory is None and supplier_id and supplier_id != "anonymous":
            try:
                db_session = SessionLocal()
                try:
                    query = db_session.query(TelemetryModel).filter(
                        TelemetryModel.supplier_id == supplier_id,
                    )
                    if sku_id:
                        query = query.filter(TelemetryModel.sku_id == sku_id)

                    fallback_records = query.order_by(
                        TelemetryModel.recorded_at.desc()
                    ).limit(90).all()

                    if fallback_records:
                        fallback_records.reverse()
                        historical_trajectory = [float(r.inventory_count) for r in fallback_records]
                        current_inventory = historical_trajectory[-1]
                        logger.info(
                            "StockoutPrediction: Fallback extracted %d days for %s",
                            len(historical_trajectory), supplier_id,
                        )
                    else:
                        record = query.order_by(
                            TelemetryModel.recorded_at.desc()
                        ).first()
                        if record:
                            current_inventory = record.inventory_count
                finally:
                    db_session.close()
            except Exception as e:
                logger.warning("StockoutPrediction: Fallback DB query failed: %s", e)

        if current_inventory is not None and current_inventory < LOW_INVENTORY_THRESHOLD:
            risk_probability = 0.9
        else:
            risk_probability = 0.1

        if not historical_trajectory and current_inventory is not None:
            historical_trajectory = [float(current_inventory)] * 90

        forecast_trajectory = (
            [max(0.0, float(current_inventory) * (1.0 - risk_probability))] * 5
            if current_inventory is not None
            else []
        )

        return StandardizedPredictionResponse(
            correlation_id=request.correlation_id,
            prediction_value=risk_probability,
            confidence_score=HEURISTIC_CONFIDENCE,
            fallback_engaged=True,
            model_version="heuristic_rule_v1",
            historical_trajectory=historical_trajectory,
            forecast_trajectory=forecast_trajectory,
        )