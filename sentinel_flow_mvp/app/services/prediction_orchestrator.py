"""Prediction Orchestrator Service.

This module implements the central routing and fallback mechanism for all
intelligence modules in Sentinel-Flow. It uses the Strategy Pattern to
dynamically route inference requests to the correct prediction module,
while guaranteeing system resilience through automatic fallback engagement.

The orchestrator ensures that:
1. Requests are routed to the correct module based on module_id.
2. If a module is not registered, a clear error is raised.
3. If a module crashes or times out, the heuristic fallback is instantly engaged.
4. Every response is standardized and traceable via correlation_id.
5. All operations are asynchronous for non-blocking execution.
6. LoRA adapters are checked before execution for canary routing.
"""

import asyncio
import logging
import random
from typing import Dict

from app.domain.schemas import (
    BaseInferenceRequest,
    ROUTE_BASE_MODEL,
    ROUTE_HEURISTIC_FALLBACK,
    ROUTE_LORA_MODEL,
    StandardizedPredictionResponse,
)
from app.services.compute_hypervisor import ComputeHypervisor
from app.services.ml_interfaces import BasePredictionModule

logger = logging.getLogger(__name__)

# Canary routing percentage: 10% of traffic goes to VALIDATING adapters
CANARY_TRAFFIC_PERCENTAGE = 0.10


class ModuleNotFoundError(Exception):
    """Custom exception raised when a requested module_id is not registered.

    This helps distinguish between "module not found" errors and
    actual model execution failures.
    """
    pass


class PredictionOrchestrator:
    """Central router and fallback manager for all prediction modules.

    This class maintains a registry of prediction modules and routes
    inference requests to the appropriate module. It wraps all module
    calls in try/except blocks to guarantee that a response is always
    returned, even if the primary ML model fails.

    All methods are asynchronous to support non-blocking I/O operations
    and allow the orchestrator to handle timeout enforcement properly.

    Attributes:
        _module_registry: Dictionary mapping module_id strings to module instances.
    """

    def __init__(self) -> None:
        """Initialize the orchestrator with an empty module registry."""
        self._module_registry: Dict[str, BasePredictionModule] = {}

    def register_module(self, module_id: str, module: BasePredictionModule) -> None:
        """Register a prediction module with the orchestrator.

        This method adds a module to the internal registry so that
        future inference requests can be routed to it.

        Args:
            module_id: Unique identifier for the module (e.g., 'demand_forecast').
            module: An instance of a class that implements BasePredictionModule.
        """
        self._module_registry[module_id] = module
        logger.info(f"Registered prediction module: {module_id}")

    def _check_lora_adapter(self, module_id: str) -> str:
        """Check the LoRA adapter registry for an ACTIVE or VALIDATING adapter.

        This method queries the database for adapters matching the requested
        module. If an ACTIVE adapter exists, it is used for all traffic.
        If a VALIDATING adapter exists, the canary router may send 10%
        of traffic to it for testing.

        Args:
            module_id: The target module name to check for adapters.

        Returns:
            The adapter ID if an active/canary adapter should be used,
            or None if no adapter is available.
        """
        try:
            # Import the database models inside the method to avoid circular imports
            from app.infrastructure.database import SessionLocal
            from app.infrastructure.db.models import LoRAAdapterRegistry

            # Open a database session to query the adapter registry
            database_session = SessionLocal()

            try:
                # Step 1: Check for an ACTIVE adapter (used for all traffic)
                active_adapter = database_session.query(LoRAAdapterRegistry).filter(
                    LoRAAdapterRegistry.module_name == module_id,
                    LoRAAdapterRegistry.status == "ACTIVE",
                ).first()

                if active_adapter is not None:
                    logger.info(
                        f"Injecting LoRA adapter '{active_adapter.id}' "
                        f"for module '{module_id}' (ACTIVE)"
                    )
                    return active_adapter.id

                # Step 2: Check for a VALIDATING adapter (canary routing)
                validating_adapter = database_session.query(LoRAAdapterRegistry).filter(
                    LoRAAdapterRegistry.module_name == module_id,
                    LoRAAdapterRegistry.status == "VALIDATING",
                ).first()

                if validating_adapter is not None:
                    # Canary logic: send 10% of traffic to the validating adapter
                    # random.random() returns a float between 0.0 and 1.0
                    # If the value is less than 0.10, this request is part of
                    # the canary test group
                    if random.random() < CANARY_TRAFFIC_PERCENTAGE:
                        logger.info(
                            f"Canary routing: injecting LoRA adapter "
                            f"'{validating_adapter.id}' for module '{module_id}' "
                            f"(10% traffic test)"
                        )
                        return validating_adapter.id
                    else:
                        logger.info(
                            f"Canary routing: using base model for module "
                            f"'{module_id}' (90% traffic group)"
                        )

            finally:
                database_session.close()

        except Exception as check_error:
            # If the adapter check fails for any reason, log the error
            # and continue with the base model (safe fallback)
            logger.warning(
                f"LoRA adapter check failed for module '{module_id}': "
                f"{str(check_error)}. Continuing with base model."
            )

        # No adapter available or canary selected the base model
        return None

    def _rollback_adapter(self, adapter_id: str) -> None:
        """Mark a LoRA adapter as ROLLED_BACK after a prediction failure.

        This method is called when a canary adapter causes a prediction
        failure. It updates the adapter's status to ROLLED_BACK so the
        orchestrator stops routing traffic to it.

        Args:
            adapter_id: The UUID of the adapter to roll back.
        """
        try:
            # Import database dependencies inside the method to avoid circular imports
            from app.infrastructure.database import SessionLocal
            from app.infrastructure.db.models import LoRAAdapterRegistry

            # Open a database session to update the adapter record
            database_session = SessionLocal()

            try:
                # Query the failed adapter record
                failed_adapter = database_session.query(LoRAAdapterRegistry).filter(
                    LoRAAdapterRegistry.id == adapter_id
                ).first()

                if failed_adapter is not None:
                    # Update the status to ROLLED_BACK so it is no longer used
                    failed_adapter.status = "ROLLED_BACK"
                    database_session.commit()

                    logger.critical(
                        f"Canary adapter '{adapter_id}' failed validation. "
                        f"Rolling back. Status set to ROLLED_BACK."
                    )

            finally:
                database_session.close()

        except Exception as rollback_error:
            # If even the rollback fails, log it but do not crash
            logger.error(
                f"Could not roll back adapter '{adapter_id}': "
                f"{str(rollback_error)}"
            )

    async def execute_prediction(
        self, request: BaseInferenceRequest
    ) -> StandardizedPredictionResponse:
        """Route and execute a prediction request with automatic fallback.

        This is the core execution method. It looks up the target module,
        checks for available LoRA adapters, attempts to run the primary
        prediction with timeout enforcement, and automatically falls back
        to the heuristic if anything goes wrong.

        If a canary LoRA adapter was active and the prediction fails, the
        adapter is automatically rolled back (status = ROLLED_BACK) and
        future traffic uses the base model.

        The try/except block guarantees that StandardizedPredictionResponse
        is always returned, preventing cascading failures in the pipeline.

        Args:
            request: The standardized inference request containing module_id and features.

        Returns:
            A StandardizedPredictionResponse from either the primary model
            or the heuristic fallback.

        Raises:
            ModuleNotFoundError: If the requested module_id is not in the registry.
        """
        # Step 1: Verify the requested module is registered
        if request.module_id not in self._module_registry:
            error_message = f"Module '{request.module_id}' is not registered in the orchestrator."
            logger.error(error_message)
            raise ModuleNotFoundError(error_message)

        # Step 2: Retrieve the target module from the registry early
        # We need it for both the hypervisor fallback path and the
        # primary execution path, so we fetch it before branching.
        target_module = self._module_registry[request.module_id]

        # ------------------------------------------------------------------
        # Step 3: Invoke the ComputeHypervisor to decide which model path
        # to use (BASE_MODEL, LORA_MODEL, or HEURISTIC_FALLBACK).
        #
        # We wrap the hypervisor call in a try/except block so that if
        # anything goes wrong inside the hypervisor (e.g., a type error),
        # the entire application does not crash. Instead, we log the
        # error and default to the safest possible route: heuristic
        # fallback, which costs zero compute budget.
        # ------------------------------------------------------------------
        try:
            # Create a fresh hypervisor instance for this request
            hypervisor = ComputeHypervisor()

            # Ask the hypervisor to decide the routing path based on
            # the request's SLA tier and remaining compute budget
            routing_decision = hypervisor.determine_route(
                sla_tier=request.sla_tier,
                compute_budget_remaining=request.compute_budget_remaining,
            )

        except Exception as hypervisor_error:
            # If the hypervisor itself throws an error, log it and
            # default to heuristic fallback (safest possible outcome)
            logger.error(
                "ComputeHypervisor raised an exception for "
                "correlation_id '%s': %s. "
                "Defaulting to ROUTE_HEURISTIC_FALLBACK.",
                request.correlation_id,
                str(hypervisor_error),
            )
            routing_decision = ROUTE_HEURISTIC_FALLBACK

        # ------------------------------------------------------------------
        # Step 4: Branch based on the hypervisor's routing decision
        #
        # If the decision is HEURISTIC_FALLBACK, we skip all model
        # inference and go directly to the deterministic fallback.
        # This conserves compute budget and guarantees a fast response.
        # ------------------------------------------------------------------
        if routing_decision == ROUTE_HEURISTIC_FALLBACK:

            # Log that the hypervisor chose to skip model inference
            logger.info(
                "Hypervisor routed correlation_id '%s' to HEURISTIC_FALLBACK. "
                "Skipping primary model execution entirely.",
                request.correlation_id,
            )

            # Execute the deterministic fallback heuristic directly
            # without attempting any model inference
            fallback_result = await target_module.heuristic_fallback(request)

            # Log that the fallback was engaged and return the result
            logger.info(
                "Heuristic fallback engaged for module '%s' "
                "(correlation_id: %s) [Hypervisor direct route].",
                request.module_id,
                request.correlation_id,
            )
            return fallback_result

        # ------------------------------------------------------------------
        # Step 5: Check for a LoRA adapter to inject
        # We only reach this point if the hypervisor chose BASE_MODEL
        # or LORA_MODEL. In either case, we check if there is an ACTIVE
        # or canary-eligible VALIDATING adapter in the database.
        # ------------------------------------------------------------------
        lora_adapter_id = self._check_lora_adapter(module_id=request.module_id)
        if lora_adapter_id is not None:
            logger.info(
                "LoRA adapter '%s' is active for module '%s'. Adapter injected.",
                lora_adapter_id,
                request.module_id,
            )

        # ------------------------------------------------------------------
        # Step 6: If the hypervisor requested LORA_MODEL but no adapter
        # exists in the database, we cannot fulfill the LoRA path.
        # In this case, we degrade gracefully to heuristic fallback
        # instead of silently upgrading to the expensive base model.
        # ------------------------------------------------------------------
        if routing_decision == ROUTE_LORA_MODEL and lora_adapter_id is None:

            logger.warning(
                "Hypervisor requested LORA_MODEL for module '%s' "
                "(correlation_id: %s), but no LoRA adapter is available. "
                "Degrading to BASE_MODEL.",
                request.module_id,
                request.correlation_id,
            )

            # Degrade to BASE_MODEL instead of heuristic fallback
            routing_decision = ROUTE_BASE_MODEL

        # ------------------------------------------------------------------
        # Step 7: Attempt primary model prediction with explicit error handling
        # This path runs for both ROUTE_BASE_MODEL and ROUTE_LORA_MODEL.
        # The difference between the two paths is handled by the adapter
        # injection above: BASE_MODEL uses the full base model while
        # LORA_MODEL uses the adapter-enhanced lightweight model.
        # ------------------------------------------------------------------
        try:
            logger.info(
                "Executing primary prediction for module '%s' "
                "(correlation_id: %s, timeout: %sms, routing: %s).",
                request.module_id,
                request.correlation_id,
                request.timeout_ms,
                routing_decision,
            )

            # Execute the module's primary predict method with timeout enforcement
            # asyncio.wait_for ensures the prediction doesn't exceed the timeout
            prediction_result = await asyncio.wait_for(
                target_module.predict(request),
                timeout=request.timeout_ms / 1000.0,  # Convert milliseconds to seconds
            )

            # Log success and return the result
            logger.info(
                "Primary prediction successful for module '%s' "
                "(correlation_id: %s, routing: %s).",
                request.module_id,
                request.correlation_id,
                routing_decision,
            )
            return prediction_result

        except asyncio.TimeoutError:
            # Handle timeout specifically
            logger.warning(
                "Primary model timed out for module '%s' "
                "(timeout: %sms). Engaging heuristic fallback. "
                "Routing was: %s.",
                request.module_id,
                request.timeout_ms,
                routing_decision,
            )
            # If a canary adapter timed out, roll it back immediately
            if lora_adapter_id is not None:
                self._rollback_adapter(adapter_id=lora_adapter_id)

        except Exception as execution_error:
            # Handle any other failure (crash, invalid input, etc.)
            logger.warning(
                "Primary model failed for module '%s': %s. "
                "Engaging heuristic fallback. Routing was: %s.",
                request.module_id,
                str(execution_error),
                routing_decision,
            )
            # If a canary adapter failed, roll it back immediately
            if lora_adapter_id is not None:
                self._rollback_adapter(adapter_id=lora_adapter_id)

        # ------------------------------------------------------------------
        # Step 8: Execute the deterministic fallback heuristic
        # This code runs only if the primary prediction failed (timeout
        # or exception). The hypervisor's HEURISTIC_FALLBACK path was
        # handled in Step 4 above.
        # ------------------------------------------------------------------
        try:
            fallback_result = await target_module.heuristic_fallback(request)

            # Log fallback engagement and return the result
            logger.info(
                "Heuristic fallback engaged for module '%s' "
                "(correlation_id: %s) [post-primary-failure].",
                request.module_id,
                request.correlation_id,
            )
            return fallback_result

        except Exception as fallback_error:
            # Critical: Even the fallback failed. This should never happen
            # with well-implemented modules, but we handle it gracefully.
            logger.critical(
                "CRITICAL: Both primary model AND fallback failed for module "
                "'%s': %s. Returning emergency default response.",
                request.module_id,
                str(fallback_error),
            )

            # Return an emergency default response to prevent total failure
            return StandardizedPredictionResponse(
                correlation_id=request.correlation_id,
                prediction_value=0.0,
                confidence_score=0.0,
                fallback_engaged=True,
                model_version="emergency_default_v1",
            )
