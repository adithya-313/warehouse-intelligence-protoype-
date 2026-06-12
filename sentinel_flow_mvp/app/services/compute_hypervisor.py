"""ComputeHypervisor — Phase 4.1 Deterministic Routing Gate.

This module implements a pure, stateless, rule-based hypervisor that
evaluates each inference request's SLA tier and remaining compute budget
to decide which model path the PredictionOrchestrator should use.

The hypervisor does NOT execute any model. It only returns a routing
decision string. This strict separation of concerns means the hypervisor
can be tested, audited, and modified independently of the ML pipeline.

Routing decisions (import from app.domain.schemas):
    ROUTE_BASE_MODEL          — Use the large, high-accuracy base model.
    ROUTE_LORA_MODEL          — Use a lightweight LoRA-adapted model.
    ROUTE_HEURISTIC_FALLBACK  — Use the deterministic heuristic fallback.
"""

import logging

from app.domain.schemas import (
    ROUTE_BASE_MODEL,
    ROUTE_HEURISTIC_FALLBACK,
    ROUTE_LORA_MODEL,
)

# Set up a logger for this module so every routing decision is observable
logger = logging.getLogger(__name__)


class ComputeHypervisor:
    """Rule-based engine that decides where to route each prediction request.

    The hypervisor examines two pieces of information from the request:
    1. sla_tier — The client's service level agreement tier.
    2. compute_budget_remaining — How much budget the client has left.

    Based on these values and the thresholds defined below, it returns
    one of three routing decisions:
        - ROUTE_BASE_MODEL:  High-cost, high-accuracy path.
        - ROUTE_LORA_MODEL:  Low-cost, good-accuracy path.
        - ROUTE_HEURISTIC_FALLBACK: Zero-cost, deterministic path.

    Attributes:
        premium_base_model_threshold (float):
            Minimum budget needed for premium clients to get the base model.
        standard_base_model_threshold (float):
            Minimum budget needed for standard clients to get the base model.
        standard_lora_model_threshold (float):
            Minimum budget needed for standard clients to get the LoRA model.
            Below this, they drop to heuristic fallback.
        basic_lora_model_threshold (float):
            Budget must be strictly above this value for basic clients
            to get the LoRA model. Otherwise they get heuristic fallback.
    """

    def __init__(self) -> None:
        """Initialize the hypervisor with default budget thresholds.

        These thresholds define the boundary between model tiers.
        They are intentionally simple and readable so that anyone
        on the team can adjust them without touching complex logic.
        """
        # Premium tier: clients pay for the best model.
        # If budget is 20.0 or more, they get the base model.
        # If budget drops below 20.0, they get the LoRA model.
        self.premium_base_model_threshold: float = 20.0

        # Standard tier: mid-tier clients.
        # Budget >= 50.0  -> base model
        # Budget >= 10.0  -> LoRA model
        # Budget <  10.0  -> heuristic fallback
        self.standard_base_model_threshold: float = 50.0
        self.standard_lora_model_threshold: float = 10.0

        # Basic tier: budget-conscious clients.
        # Budget > 30.0   -> LoRA model
        # Budget <= 30.0  -> heuristic fallback
        self.basic_lora_model_threshold: float = 30.0

    def determine_route(
        self,
        sla_tier: str,
        compute_budget_remaining: float,
    ) -> str:
        """Decide which model path to use for a given request.

        This method applies a deterministic if/elif/else decision tree.
        It does NOT call any model or database. It is a pure function
        that maps (sla_tier, budget) -> routing_decision.

        Args:
            sla_tier:
                The client's SLA tier. Must be lowercase 'premium',
                'standard', or 'basic'. (The schema validator in
                BaseInferenceRequest already sanitizes this.)
            compute_budget_remaining:
                The remaining compute budget for this client.
                A value of 0.0 or less means the budget is exhausted.

        Returns:
            One of: ROUTE_BASE_MODEL, ROUTE_LORA_MODEL,
            ROUTE_HEURISTIC_FALLBACK.

        Logic summary:
            - Budget exhausted (<= 0.0) -> HEURISTIC_FALLBACK always.
            - Premium:  budget >= 20.0  -> BASE_MODEL
                        else            -> LORA_MODEL
            - Standard: budget >= 50.0  -> BASE_MODEL
                        budget >= 10.0  -> LORA_MODEL
                        else            -> HEURISTIC_FALLBACK
            - Basic:    budget >  30.0  -> LORA_MODEL
                        else            -> HEURISTIC_FALLBACK
        """
        # ------------------------------------------------------------------
        # Step 1: Sanitize the SLA tier input
        # We call .lower() again as a safety net in case this method is
        # called directly (not through the Pydantic schema).
        # ------------------------------------------------------------------
        sanitized_sla_tier = sla_tier.lower()

        # ------------------------------------------------------------------
        # Step 2: Check if the compute budget is exhausted
        # If the remaining budget is zero or negative, there is no point
        # in spending compute resources. We immediately route to the
        # zero-cost heuristic fallback, regardless of the SLA tier.
        # ------------------------------------------------------------------
        if compute_budget_remaining <= 0.0:
            logger.info(
                "ComputeHypervisor decision: ROUTE_HEURISTIC_FALLBACK. "
                "Reason: compute_budget_remaining is %.2f (exhausted). "
                "SLA tier was '%s'.",
                compute_budget_remaining,
                sanitized_sla_tier,
            )
            return ROUTE_HEURISTIC_FALLBACK

        # ------------------------------------------------------------------
        # Step 3: Premium tier routing
        # Premium clients have paid for guaranteed access to the best model.
        # As long as their budget is at or above the premium threshold,
        # they get the full base model. If their budget is low but not
        # exhausted, they drop down to the cheaper LoRA model.
        # ------------------------------------------------------------------
        if sanitized_sla_tier == "premium":
            if compute_budget_remaining >= self.premium_base_model_threshold:
                logger.info(
                    "ComputeHypervisor decision: ROUTE_BASE_MODEL. "
                    "Reason: sla_tier is 'premium' and budget (%.2f) "
                    "is >= threshold (%.2f).",
                    compute_budget_remaining,
                    self.premium_base_model_threshold,
                )
                return ROUTE_BASE_MODEL
            else:
                logger.info(
                    "ComputeHypervisor decision: ROUTE_LORA_MODEL. "
                    "Reason: sla_tier is 'premium' but budget (%.2f) "
                    "is below threshold (%.2f). Degrading to LoRA.",
                    compute_budget_remaining,
                    self.premium_base_model_threshold,
                )
                return ROUTE_LORA_MODEL

        # ------------------------------------------------------------------
        # Step 4: Standard tier routing
        # Standard clients get the base model only when their budget is
        # high (>= 50.0). At medium budget they get LoRA. At low budget
        # (below 10.0) they fall back to the heuristic.
        # ------------------------------------------------------------------
        if sanitized_sla_tier == "standard":
            if compute_budget_remaining >= self.standard_base_model_threshold:
                logger.info(
                    "ComputeHypervisor decision: ROUTE_BASE_MODEL. "
                    "Reason: sla_tier is 'standard' and budget (%.2f) "
                    "is >= threshold (%.2f).",
                    compute_budget_remaining,
                    self.standard_base_model_threshold,
                )
                return ROUTE_BASE_MODEL

            if compute_budget_remaining >= self.standard_lora_model_threshold:
                logger.info(
                    "ComputeHypervisor decision: ROUTE_LORA_MODEL. "
                    "Reason: sla_tier is 'standard' and budget (%.2f) "
                    "is between thresholds (%.2f - %.2f).",
                    compute_budget_remaining,
                    self.standard_lora_model_threshold,
                    self.standard_base_model_threshold,
                )
                return ROUTE_LORA_MODEL

            logger.info(
                "ComputeHypervisor decision: ROUTE_HEURISTIC_FALLBACK. "
                "Reason: sla_tier is 'standard' but budget (%.2f) "
                "is below minimum threshold (%.2f).",
                compute_budget_remaining,
                self.standard_lora_model_threshold,
            )
            return ROUTE_HEURISTIC_FALLBACK

        # ------------------------------------------------------------------
        # Step 5: Basic tier (and unknown tiers) routing
        # Basic clients never get the expensive base model. They get the
        # LoRA model only if their budget is reasonably healthy (> 30.0).
        # Otherwise they are routed directly to the heuristic fallback.
        #
        # We also handle unknown SLA tiers here by treating them as
        # "basic". This is a safe default because basic clients consume
        # the least compute resources.
        # ------------------------------------------------------------------
        if compute_budget_remaining > self.basic_lora_model_threshold:
            logger.info(
                "ComputeHypervisor decision: ROUTE_LORA_MODEL. "
                "Reason: sla_tier is '%s' and budget (%.2f) "
                "is above threshold (%.2f).",
                sanitized_sla_tier,
                compute_budget_remaining,
                self.basic_lora_model_threshold,
            )
            return ROUTE_LORA_MODEL
        else:
            logger.info(
                "ComputeHypervisor decision: ROUTE_HEURISTIC_FALLBACK. "
                "Reason: sla_tier is '%s' and budget (%.2f) "
                "is at or below threshold (%.2f).",
                sanitized_sla_tier,
                compute_budget_remaining,
                self.basic_lora_model_threshold,
            )
            return ROUTE_HEURISTIC_FALLBACK
