"""Demand Forecasting Module.

This module implements demand forecasting using the amazon/chronos-t5-mini
base model, dynamically hot-swapping supplier-specific LoRA adapters.
"""

import asyncio
import gzip
import json
import logging
import numpy as np
import os
import hashlib
import time
import redis.asyncio as aioredis
import torch
from typing import List

from app.domain.schemas import BaseInferenceRequest, StandardizedPredictionResponse
from app.services.ml_interfaces import BasePredictionModule
from app.services.models import adapter_lock
from app.infrastructure.database import SessionLocal
from app.infrastructure.models import TelemetryModel
from app.infrastructure.db.models import LoRAAdapterRegistry

logger = logging.getLogger(__name__)

SAFE_DEFAULT_DEMAND = 50.0
HEURISTIC_CONFIDENCE = 0.4
ML_MODEL_CONFIDENCE = 0.85

CACHE_TTL_SECONDS = 3600

def _get_redis_client() -> aioredis.Redis:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return aioredis.from_url(redis_url, decode_responses=False)

def _cache_key(supplier_id: str, sku_id: str) -> str:
    return f"forecast:{supplier_id}:{sku_id or '*'}"

class DemandForecastingModule(BasePredictionModule):
    """Demand forecasting module using Chronos-T5 with dynamic LoRA adapters."""

    async def predict(self, request: BaseInferenceRequest) -> StandardizedPredictionResponse:
        logger.info(f"DemandForecast: Starting primary prediction (correlation_id: {request.correlation_id})")

        supplier_id = request.supplier_id or request.features.get("supplier_id") or request.client_id
        if not supplier_id or supplier_id == "anonymous":
            raise ValueError("DemandForecast: supplier_id is missing from request and features")
            
        sku_id = request.sku_id or request.features.get("sku_id")

        # Access the globally loaded ChronosPipeline from FastAPI app state
        try:
            from app.main import app
            pipeline = getattr(app.state, "chronos_pipeline", None)
            if pipeline is None:
                raise RuntimeError("ChronosPipeline is not initialized in app.state")
        except ImportError:
            raise RuntimeError("Could not import app.main.app to access global pipeline")

        # Redis cache check (GZIP compressed)
        redis_client = _get_redis_client()
        try:
            cached_raw = await redis_client.get(_cache_key(supplier_id, sku_id))
            if cached_raw:
                decompressed = gzip.decompress(cached_raw).decode()
                cached_data = json.loads(decompressed)
                logger.info(f"DemandForecast: Cache HIT for {supplier_id}/{sku_id}")
                await redis_client.aclose()
                return StandardizedPredictionResponse(**cached_data)
        except Exception as cache_err:
            logger.warning(f"DemandForecast: Cache read failed (continuing): {cache_err}")

        db_session = SessionLocal()
        adapter_used = False
        predicted_demand = 0.0

        try:
            # Query for the latest ACTIVE adapter for this supplier
            adapter_record = db_session.query(LoRAAdapterRegistry).filter(
                LoRAAdapterRegistry.module_name == "demand_forecast",
                LoRAAdapterRegistry.supplier_id == supplier_id,
                LoRAAdapterRegistry.status == "ACTIVE"
            ).order_by(LoRAAdapterRegistry.created_at.desc()).first()

            # Fetch the exactly trailing 90 days of chronological telemetry records
            query = db_session.query(TelemetryModel).filter(
                TelemetryModel.supplier_id == supplier_id
            )
            if sku_id:
                query = query.filter(TelemetryModel.sku_id == sku_id)
                
            records = query.order_by(TelemetryModel.recorded_at.desc()).limit(90).all()

            if not records:
                raise ValueError(f"No telemetry records found for supplier_id={supplier_id}")

            # Time series must be chronological
            records.reverse()
            inventory_data = [float(r.inventory_count) for r in records]

            # Enforce strict (1, 90) dimension
            if len(inventory_data) < 90:
                # Pad left with the oldest value
                padding = [inventory_data[0]] * (90 - len(inventory_data))
                inventory_data = padding + inventory_data
            elif len(inventory_data) > 90:
                # Truncate left
                inventory_data = inventory_data[-90:]

            context_tensor = torch.tensor(inventory_data, dtype=torch.float32).view(1, 90)

            swap_in_latency_ms = 0.0
            compute_latency_ms = 0.0
            swap_out_latency_ms = 0.0

            # CRITICAL: We lock the base model here because it is a shared singleton.
            # If two requests swap weights simultaneously, the tensors will corrupt.
            async with adapter_lock:
                # Load LoRA adapter if available, otherwise fallback to base model
                if adapter_record and adapter_record.adapter_weights_path:
                    safetensors_path = os.path.join(adapter_record.adapter_weights_path, "adapter_model.safetensors")
                    
                    if not os.path.exists(safetensors_path):
                        logger.warning(f"Adapter safetensors path does not exist: {safetensors_path}. Skipping adapter.")
                        adapter_used = False
                    else:
                            # --- Cryptographic Checksum Validation ---
                            sha256_hash = hashlib.sha256()
                            # Read file in chunks to prevent memory spikes on large model files
                            with open(safetensors_path, "rb") as f:
                                for byte_block in iter(lambda: f.read(4096), b""):
                                    sha256_hash.update(byte_block)
                            
                            computed_checksum = sha256_hash.hexdigest()
                            if adapter_record.checksum and computed_checksum != adapter_record.checksum:
                                logger.critical(f"Checksum mismatch for adapter {adapter_record.id}. Expected {adapter_record.checksum}, got {computed_checksum}")
                                raise ValueError("Adapter checksum mismatch")

                            logger.info(f"Loading LoRA adapter for {supplier_id} from {adapter_record.adapter_weights_path}")
                            t0_swap_in = time.perf_counter()
                            pipeline.model.load_adapter(adapter_record.adapter_weights_path, adapter_name="current_lora")
                            pipeline.model.set_adapter("current_lora")
                            swap_in_latency_ms = (time.perf_counter() - t0_swap_in) * 1000.0
                            adapter_used = True

                if not adapter_used:
                    logger.warning(f"No ACTIVE adapter successfully loaded for supplier {supplier_id}. Falling back to zero-shot base Chronos model.")
                    # Ensure no adapter is accidentally active
                    try:
                        pipeline.model.disable_adapters()
                    except Exception:
                        pass

                try:
                    # Execute chronos prediction (predicts next 5 steps)
                    t0_compute = time.perf_counter()
                    forecast = await asyncio.to_thread(pipeline.predict, context_tensor, prediction_length=5)
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
                    predicted_demand = float(forecast_trajectory[0])
                    historical_trajectory = inventory_data

                finally:
                    # Clean up adapter to keep VRAM clean while still holding the lock
                    if adapter_used:
                        t0_swap_out = time.perf_counter()
                        try:
                            pipeline.model.delete_adapter("current_lora")
                        except Exception as e:
                            logger.warning(f"Failed to delete adapter 'current_lora': {e}")
                        try:
                            pipeline.model.disable_adapters()
                        except Exception:
                            pass
                        swap_out_latency_ms = (time.perf_counter() - t0_swap_out) * 1000.0

        except torch.cuda.OutOfMemoryError as oom_error:
            logger.error(f"DemandForecast OOM: {oom_error}. Clearing CUDA cache.")
            torch.cuda.empty_cache()
            await redis_client.aclose()
            raise
        except Exception as execution_error:
            logger.error(f"DemandForecast execution failed: {execution_error}")
            await redis_client.aclose()
            raise
        finally:
            db_session.close()

        logger.info(f"DemandForecast: Primary prediction complete. Value={predicted_demand:.2f}")
        print(f"DEBUG PAYLOAD - Hist Len: {len(historical_trajectory)}, Fore Len: {len(forecast_trajectory)}")
        print(f"DEBUG PAYLOAD SAMPLE - Hist: {historical_trajectory[-5:]}, Fore: {forecast_trajectory}")

        response = StandardizedPredictionResponse(
            correlation_id=request.correlation_id,
            prediction_value=predicted_demand,
            confidence_score=ML_MODEL_CONFIDENCE,
            fallback_engaged=False,
            model_version="chronos_lora_v1" if adapter_used else "chronos_base_v1",
            historical_trajectory=historical_trajectory,
            forecast_trajectory=forecast_trajectory,
            execution_metadata={
                "swap_in_latency_ms": swap_in_latency_ms,
                "compute_latency_ms": compute_latency_ms,
                "swap_out_latency_ms": swap_out_latency_ms,
            }
        )

        # Write to Redis cache with GZIP compression
        try:
            serialized = response.model_dump_json().encode('utf-8')
            compressed = gzip.compress(serialized)
            await redis_client.setex(_cache_key(supplier_id, sku_id), CACHE_TTL_SECONDS, compressed)
        except Exception as cache_err:
            logger.warning(f"DemandForecast: Cache write failed: {cache_err}")
        finally:
            await redis_client.aclose()

        return response

    async def heuristic_fallback(self, request: BaseInferenceRequest) -> StandardizedPredictionResponse:
        logger.info(f"DemandForecast: Engaging heuristic fallback (correlation_id: {request.correlation_id})")

        supplier_id = request.supplier_id or request.features.get("supplier_id") or request.client_id
        sku_id = request.sku_id or request.features.get("sku_id")
        average_demand = SAFE_DEFAULT_DEMAND

        if supplier_id and supplier_id != "anonymous":
            try:
                db_session = SessionLocal()
                try:
                    query = db_session.query(TelemetryModel).filter(
                        TelemetryModel.supplier_id == supplier_id
                    )
                    if sku_id:
                        query = query.filter(TelemetryModel.sku_id == sku_id)
                        
                    records = query.order_by(TelemetryModel.recorded_at.desc()).limit(30).all()

                    if records:
                        records.reverse()
                        inventory_values = [r.inventory_count for r in records]
                        average_demand = float(np.mean(inventory_values))
                        logger.info(f"DemandForecast: SMA fallback from DB. "
                                    f"Supplier={supplier_id}, Window=30d, "
                                    f"Mean={average_demand:.2f}")
                    else:
                        logger.warning(f"DemandForecast: No telemetry for {supplier_id}")
                finally:
                    db_session.close()
            except Exception as e:
                logger.error(f"DemandForecast: DB query failed in fallback: {e}")

        return StandardizedPredictionResponse(
            correlation_id=request.correlation_id,
            prediction_value=average_demand,
            confidence_score=HEURISTIC_CONFIDENCE,
            fallback_engaged=True,
            model_version="heuristic_sma_v1",
        )
