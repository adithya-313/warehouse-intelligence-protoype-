"""FastAPI application entry point.

This module initializes and configures the FastAPI application instance.
All routes are registered here and the application is started via uvicorn.

The application uses a lifespan context manager to initialize the
PredictionOrchestrator and register all intelligence modules during startup.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager

import anyio

# Configure structured JSON logging for the API process globally at the top
from app.core.logging import configure_logging
configure_logging(level=logging.INFO, json_output=True)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError, OperationalError
import redis.asyncio as aioredis
import redis.exceptions as redis_exceptions
import torch
from chronos import ChronosPipeline

from app.api.dependencies import verify_api_key

from app.api.v1 import audit, federated, ingestion, risk, stream_router, stats
from app.core.config import get_application_settings
from app.core.metrics import get_metrics_app
from app.domain.schemas import (
    BaseInferenceRequest,
    HardwareInferenceRequest,
    ProcurementDecisionResponse,
    ProcurementOptimizationRequest,
    StandardizedPredictionResponse,
)
from app.infrastructure.database import SessionLocal, get_database_session
from app.infrastructure.db.models import LoRAAdapterRegistry
from app.infrastructure.models import SupplierModel
from app.services.models.demand_forecast import DemandForecastingModule
from app.services.models.stockout_prediction import StockoutPredictionModule
from app.services.prediction_orchestrator import PredictionOrchestrator
from app.services.procurement_engine import ProcurementOptimizationEngine


# Global orchestrator instance - initialized during application startup
prediction_orchestrator: PredictionOrchestrator = PredictionOrchestrator()

# Global procurement engine instance - initialized during application startup
procurement_engine: ProcurementOptimizationEngine = ProcurementOptimizationEngine()


@asynccontextmanager
async def application_lifespan(application: FastAPI):
    """Application lifespan context manager for startup and shutdown events.

    This function runs during application startup to initialize all
    intelligence modules and register them with the orchestrator.
    It also handles cleanup during shutdown.

    Args:
        application: The FastAPI application instance.
    """
    # ===== STARTUP PHASE =====
    logger.info("=" * 60)
    logger.info("SENTINEL-FLOW: Application Startup")
    logger.info("=" * 60)

    # Step 0: Expand the anyio thread pool for synchronous route offloading
    # FastAPI offloads sync def routes to anyio's thread pool (default 40 tokens).
    # With DB pool at 50 and concurrency up to 200, we need more threads.
    anyio.to_thread.current_default_thread_limiter().total_tokens = 200
    logger.info("Expanded anyio thread pool to 200 tokens.")

    # Step 1: Initialize Base Chronos Pipeline
    logger.info("Loading base Chronos-T5 model into memory...")
    try:
        application.state.chronos_pipeline = ChronosPipeline.from_pretrained(
            "amazon/chronos-t5-mini",
            device_map="cuda" if torch.cuda.is_available() else "cpu",
            torch_dtype=torch.float32
        )
        logger.info("Chronos base model loaded successfully.")
    except Exception as e:
        logger.error(f"Failed to load Chronos base model: {e}")

    # Step 1: Instantiate all intelligence modules
    logger.info("Initializing intelligence modules...")

    demand_forecast_module = DemandForecastingModule()
    stockout_prediction_module = StockoutPredictionModule()

    logger.info("Modules instantiated successfully.")

    # Step 2: Register modules with the global orchestrator
    logger.info("Registering modules with PredictionOrchestrator...")

    prediction_orchestrator.register_module(
        module_id="demand_forecast",
        module=demand_forecast_module,
    )

    prediction_orchestrator.register_module(
        module_id="stockout_prediction",
        module=stockout_prediction_module,
    )

    logger.info("All modules registered successfully.")
    logger.info(f"Registered modules: {list(prediction_orchestrator._module_registry.keys())}")
    logger.info("=" * 60)

    # Yield control to the application - this is where the app runs
    yield

    # ===== SHUTDOWN PHASE =====
    logger.info("=" * 60)
    logger.info("SENTINEL-FLOW: Application Shutdown")
    logger.info("=" * 60)

    logger.info("Cleaning up prediction orchestrator...")
    prediction_orchestrator._module_registry.clear()
    logger.info("Shutdown complete.")


def create_application() -> FastAPI:
    """Create and configure the FastAPI application instance.

    This function creates a new FastAPI application, registers all routers,
    and applies any middleware or event handlers needed for the application.

    Returns:
        A fully configured FastAPI application instance.
    """
    application_settings = get_application_settings()

    application_instance = FastAPI(
        title=application_settings.application_name,
        version=application_settings.application_version,
        debug=application_settings.debug_mode,
        lifespan=application_lifespan,
    )

    # CORS — allow the Next.js frontend (localhost:3000) to call the API
    application_instance.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global exception handlers — catch and normalize errors before they
    # reach FastAPI's default 500 handler which can leak stack traces.

    # Catches Database crashes globally to prevent 500 stack trace leaks
    @application_instance.exception_handler(SQLAlchemyError)
    async def sqlalchemy_exception_handler(
        request: Request, exc: SQLAlchemyError
    ) -> JSONResponse:
        logger.error(f"SQLAlchemy error: {str(exc)} on {request.method} {request.url.path}")
        return JSONResponse(
            status_code=503,
            headers={"Retry-After": "30"},
            content={"error": "Database Service Unavailable", "code": "DB_503"}
        )

    # Catches Operational Database crashes globally
    @application_instance.exception_handler(OperationalError)
    async def db_operational_exception_handler(
        request: Request, exc: OperationalError
    ) -> JSONResponse:
        logger.error(f"Database connection error: {str(exc)} on {request.method} {request.url.path}")
        return JSONResponse(
            status_code=503,
            headers={"Retry-After": "30"},
            content={"error": "Database Connection Refused", "code": "DB_503"}
        )

    # Catches Redis crashes globally to prevent 500 stack trace leaks
    @application_instance.exception_handler(redis_exceptions.RedisError)
    async def redis_exception_handler(
        request: Request, exc: redis_exceptions.RedisError
    ) -> JSONResponse:
        logger.error(f"Redis error: {str(exc)} on {request.method} {request.url.path}")
        return JSONResponse(
            status_code=503,
            headers={"Retry-After": "30"},
            content={"error": "Cache Service Unavailable", "code": "REDIS_503"}
        )

    application_instance.include_router(
        router=stats.router,
        prefix="/api/v1/system",
        tags=["System"]
    )

    # Register the ingestion API routes
    application_instance.include_router(
        router=ingestion.router,
        prefix="/api/v1/ingestion",
        tags=["ingestion"],
        dependencies=[Depends(verify_api_key)]
    )

    # Register the immutable audit ledger API routes
    application_instance.include_router(
        router=audit.router,
        prefix="/api/v1/audit",
        tags=["audit"],
        dependencies=[Depends(verify_api_key)]
    )

    # Register the Redis Stream telemetry ingestion routes
    application_instance.include_router(
        router=stream_router.router,
        prefix="/api/v1/stream",
        tags=["stream"],
        dependencies=[Depends(verify_api_key)]
    )

    # Register the federated learning weight aggregation routes
    application_instance.include_router(
        router=federated.router,
        prefix="/api/v1/federated",
        tags=["federated"],
        dependencies=[Depends(verify_api_key)]
    )

    # Register the risk dashboard routes (public — no API key required)
    application_instance.include_router(
        router=risk.router,
        prefix="/api/v1/risk",
        tags=["risk"],
    )

    # Mount the Prometheus metrics endpoint at /metrics
    # This allows Prometheus to scrape metrics from the API
    metrics_app = get_metrics_app()
    application_instance.mount("/metrics", metrics_app)

    # Register the prediction API endpoint
    @application_instance.post(
        path="/api/v1/predict",
        status_code=202,
        tags=["prediction"],
        summary="Execute ML Prediction",
        description="Route an inference request to the appropriate intelligence module.",
        dependencies=[Depends(verify_api_key)]
    )
    async def execute_prediction_endpoint(
        hardware_request: HardwareInferenceRequest,
        request: Request,
    ):
        """Execute a prediction request through the orchestrator.

        This endpoint accepts a HardwareInferenceRequest, verifies the domain
        entities against the database, maps it to a BaseInferenceRequest,
        routes it to the appropriate module via the PredictionOrchestrator,
        and returns a StandardizedPredictionResponse.
        """
        country = request.headers.get("CF-IPCountry", "Unknown")
        
        logger.info(
            f"Prediction endpoint called: module_id={hardware_request.module_id}, "
            f"supplier_id={hardware_request.supplier_id}, sku_id={hardware_request.sku_id}, "
            f"country={country}"
        )

        # Domain Validation
        database_session = SessionLocal()
        try:
            import asyncio
            def check_supplier():
                return database_session.query(SupplierModel).filter(
                    SupplierModel.supplier_id == hardware_request.supplier_id
                ).first()
            supplier_exists = await asyncio.to_thread(check_supplier)
            if not supplier_exists:
                raise HTTPException(
                    status_code=404, 
                    detail=f"Supplier '{hardware_request.supplier_id}' not found in hardware domain."
                )
            
            # Note: We aren't making an explicit SKU table query here because SKUs are 
            # currently tracked inside telemetry. In a full system, we'd query a products table.
        finally:
            database_session.close()

        # Map strictly to the internal orchestrator contract
        features: dict = {"country": country}
        if hardware_request.current_inventory is not None:
            features["current_inventory"] = hardware_request.current_inventory
        if hardware_request.lead_time_days is not None:
            features["lead_time_days"] = hardware_request.lead_time_days

        inference_request = BaseInferenceRequest(
            client_id=hardware_request.supplier_id,
            module_id=hardware_request.module_id,
            supplier_id=hardware_request.supplier_id,
            sku_id=hardware_request.sku_id,
            asset_id=hardware_request.sku_id, # Map sku_id to asset_id for predictive maintenance
            route_id=hardware_request.route_id,
            features=features,
            compute_budget_remaining=hardware_request.compute_budget,
            timeout_ms=15000,
            sla_tier="premium"
        )

        # Dispatch to celery queue
        from app.services.worker_tasks import predict_forecast_task
        task = await asyncio.to_thread(predict_forecast_task.delay, inference_request.model_dump())

        logger.info(
            f"Prediction dispatched to Celery: module_id={inference_request.module_id}, "
            f"task_id={task.id}"
        )

        return {"status": "Processing", "task_id": task.id}
        
    from celery.result import AsyncResult
    from app.core.celery_app import celery_application
    
    @application_instance.get(
        path="/api/v1/tasks/{task_id}",
        tags=["prediction"],
        dependencies=[Depends(verify_api_key)]
    )
    def get_task_status(task_id: str):
        try:
            task_result = AsyncResult(task_id, app=celery_application)
            if task_result.state == "PENDING":
                return {"status": "PENDING"}
            elif task_result.state == "SUCCESS":
                return {"status": "SUCCESS", "result": task_result.result}
            else:
                return {"status": task_result.state, "error": str(task_result.info)}
        except redis_exceptions.RedisError as redis_err:
            logger.error(f"Redis backend unreachable while fetching task {task_id}: {str(redis_err)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Backend task queue is currently unreachable.",
                headers={"Retry-After": "30"}
            )
        except Exception as task_error:
            logger.error(
                "Failed to fetch task status for %s: %s",
                task_id, str(task_error),
            )
            from app.core.exceptions import raise_http_exception
            raise_http_exception(
                status_code=status.HTTP_502_BAD_GATEWAY,
                message="Failed to retrieve task status from worker backend",
                error_code="TASK_STATUS_FAILED",
                details=str(task_error),
            )

    # Register the procurement optimization API endpoint
    @application_instance.post(
        path="/api/v1/optimize_procurement",
        response_model=ProcurementDecisionResponse,
        tags=["procurement"],
        summary="Optimize Procurement Decision",
        description="Calculate optimal reorder quantity and select the best supplier.",
        dependencies=[Depends(verify_api_key)]
    )
    def optimize_procurement_endpoint(
        procurement_request: ProcurementOptimizationRequest,
    ) -> ProcurementDecisionResponse:
        """Execute procurement optimization through the engine.

        This endpoint accepts a ProcurementOptimizationRequest, calculates
        the optimal reorder quantity based on demand and capacity, ranks
        available suppliers using a deterministic scoring heuristic, and
        returns a complete procurement decision.

        Args:
            procurement_request: The procurement optimization request.

        Returns:
            ProcurementDecisionResponse with the optimal order details.
        """
        logger.info(
            f"Procurement endpoint called: sku_id={procurement_request.sku_id}, "
            f"suppliers_count={len(procurement_request.available_suppliers)}"
        )

        # Execute optimization through the engine
        decision_result = procurement_engine.optimize(
            request=procurement_request,
        )

        logger.info(
            f"Procurement complete: sku_id={procurement_request.sku_id}, "
            f"reorder_quantity={decision_result.reorder_quantity}, "
            f"selected_supplier={decision_result.selected_supplier_id}"
        )

        return decision_result

    # ------------------------------------------------------------------
    # Public read-only endpoints (no API key required)
    # These expose non-sensitive supplier metadata and adapter registry
    # so the frontend can bootstrap on page load.
    # ------------------------------------------------------------------

    @application_instance.get(
        path="/api/v1/suppliers",
        tags=["suppliers"],
        summary="List Suppliers",
        description="Retrieve all supplier IDs from the database."
    )
    def list_suppliers():
        """Return the list of known supplier IDs."""
        database_session = SessionLocal()
        try:
            suppliers = (
                database_session.query(SupplierModel.supplier_id)
                .order_by(SupplierModel.supplier_id)
                .all()
            )
            return [{"supplier_id": row[0]} for row in suppliers]
        finally:
            database_session.close()

    @application_instance.get(
        path="/api/v1/adapters",
        tags=["adapters"],
        summary="List LoRA Adapters",
        description="Retrieve all LoRA adapters from the registry."
    )
    def list_adapters():
        """Retrieve all LoRA adapters from the database registry."""
        database_session = SessionLocal()
        try:
            rows = database_session.execute(
                text(
                    "SELECT id, module_name, base_model_version, adapter_weights_path, status, created_at "
                    "FROM lora_adapter_registry ORDER BY created_at DESC"
                )
            ).fetchall()
            return [
                {
                    "id": row[0],
                    "module_name": row[1],
                    "base_model_version": row[2],
                    "adapter_weights_path": row[3],
                    "status": row[4],
                    "created_at": row[5].isoformat() if row[5] else None,
                }
                for row in rows
            ]
        finally:
            database_session.close()

    return application_instance


# Create the application instance
app: FastAPI = create_application()
