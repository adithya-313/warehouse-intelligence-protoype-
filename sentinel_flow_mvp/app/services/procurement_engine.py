"""Procurement Optimization Engine.

This module implements deterministic scoring heuristics to select the optimal
supplier and calculate reorder quantities based on inputs from the Phase 2.2
forecasting modules.

The engine follows a transparent, step-by-step mathematical approach to ensure
junior engineers can easily audit, adjust, and extend the weighting logic.
"""

import logging
from typing import List, Optional

from app.domain.schemas import (
    ProcurementDecisionResponse,
    ProcurementOptimizationRequest,
    SupplierOption,
)

logger = logging.getLogger(__name__)

# Safety stock percentage: We keep 20% extra inventory to buffer against demand spikes
SAFETY_STOCK_PERCENTAGE = 0.20


class ProcurementOptimizationEngine:
    """Core engine for calculating optimal reorder quantities and selecting suppliers.

    This class uses deterministic business rules to balance inventory levels,
    warehouse capacity, supplier reliability, cost, and lead times.
    """

    def calculate_reorder_quantity(
        self,
        current_inventory: int,
        predicted_demand: int,
        warehouse_capacity: int,
    ) -> int:
        """Calculate the optimal quantity to reorder based on demand and capacity.

        This method applies four strict business rules:
        1. Safety stock is 20% of predicted demand.
        2. Target inventory = predicted_demand + safety_stock.
        3. Reorder quantity = Target inventory - current_inventory.
        4. If reorder quantity + current_inventory > capacity, cap it at capacity.

        Args:
            current_inventory: Current stock level in the warehouse.
            predicted_demand: Forecasted demand from the demand forecasting module.
            warehouse_capacity: Maximum storage capacity of the warehouse.

        Returns:
            The optimal reorder quantity (0 if inventory is sufficient).
        """
        logger.info(
            f"Calculating reorder quantity: inventory={current_inventory}, "
            f"demand={predicted_demand}, capacity={warehouse_capacity}"
        )

        # Rule 1: Calculate safety stock (20% buffer)
        safety_stock = predicted_demand * SAFETY_STOCK_PERCENTAGE

        # Rule 2: Calculate target inventory level
        target_inventory = predicted_demand + safety_stock

        # Rule 3: Calculate raw reorder quantity
        raw_reorder_quantity = target_inventory - current_inventory

        # If current inventory already meets or exceeds target, no reorder needed
        if raw_reorder_quantity <= 0:
            logger.info("Current inventory meets target. Reorder quantity: 0")
            return 0

        # Rule 4: Respect warehouse capacity ceiling
        # Maximum we can order is capacity minus what we already have
        max_possible_order = warehouse_capacity - current_inventory

        # Cap the order at the maximum possible amount
        if raw_reorder_quantity > max_possible_order:
            logger.info(
                f"Reorder quantity capped by warehouse capacity: "
                f"{raw_reorder_quantity} -> {max_possible_order}"
            )
            return max_possible_order

        logger.info(f"Calculated reorder quantity: {raw_reorder_quantity}")
        return raw_reorder_quantity

    def rank_suppliers(
        self,
        suppliers: List[SupplierOption],
        quantity: int,
    ) -> Optional[SupplierOption]:
        """Rank suppliers using a deterministic scoring heuristic.

        This method calculates a score for each supplier based on:
        - Reliability (higher is better)
        - Unit cost (lower is better)
        - Transport cost (lower is better, amortized over quantity)
        - Lead time (lower is better)

        Formula: score = (reliability_score * 100) / (unit_cost + transport_cost_per_unit + lead_time_days)

        Args:
            suppliers: List of potential suppliers to evaluate.
            quantity: The reorder quantity (used to amortize transport cost).

        Returns:
            The supplier with the highest score, or None if quantity is 0.
        """
        # If no quantity is needed, no supplier is required
        if quantity == 0:
            logger.info("Reorder quantity is 0. No supplier selection needed.")
            return None

        if not suppliers:
            logger.warning("No suppliers provided for ranking.")
            return None

        logger.info(f"Ranking {len(suppliers)} suppliers for quantity: {quantity}")

        best_supplier = None
        highest_score = -1.0

        # Iterate through each supplier to calculate their score
        for supplier in suppliers:
            # Step 1: Calculate transport cost per unit
            # We divide total transport cost by quantity to get the per-unit impact
            transport_cost_per_unit = supplier.transport_cost / quantity

            # Step 2: Calculate total effective cost per unit
            # This combines the base unit cost and the amortized transport cost
            total_cost_per_unit = supplier.unit_cost + transport_cost_per_unit

            # Step 3: Calculate the denominator for the scoring formula
            # We add lead time days to the cost to penalize slow suppliers
            # This balances speed (lead time) against financial cost
            cost_and_time_factor = total_cost_per_unit + supplier.lead_time_days

            # Step 4: Prevent division by zero
            # If cost and time factor is somehow 0, use a small epsilon
            if cost_and_time_factor == 0:
                cost_and_time_factor = 0.001

            # Step 5: Calculate the final score
            # Higher reliability increases the score (numerator)
            # Higher cost and lead time decrease the score (denominator)
            # We multiply reliability by 100 to scale it to a comparable range
            supplier_score = (supplier.reliability_score * 100) / cost_and_time_factor

            logger.info(
                f"Supplier {supplier.supplier_id}: "
                f"reliability={supplier.reliability_score}, "
                f"cost_per_unit={total_cost_per_unit:.2f}, "
                f"lead_time={supplier.lead_time_days}, "
                f"score={supplier_score:.4f}"
            )

            # Track the supplier with the highest score
            if supplier_score > highest_score:
                highest_score = supplier_score
                best_supplier = supplier

        if best_supplier is not None:
            logger.info(
                f"Selected supplier: {best_supplier.supplier_id} "
                f"(score: {highest_score:.4f})"
            )

        return best_supplier

    def optimize(
        self, request: ProcurementOptimizationRequest
    ) -> ProcurementDecisionResponse:
        """Execute the full procurement optimization workflow.

        This method orchestrates the reorder quantity calculation and
        supplier ranking to produce a complete procurement decision.

        Args:
            request: The procurement optimization request containing inventory,
                     demand, capacity, and supplier options.

        Returns:
            A ProcurementDecisionResponse with the optimal order details.
        """
        logger.info(f"Starting procurement optimization for SKU: {request.sku_id}")

        # Step 1: Calculate how much we need to order
        reorder_quantity = self.calculate_reorder_quantity(
            current_inventory=request.current_inventory,
            predicted_demand=request.predicted_demand,
            warehouse_capacity=request.warehouse_capacity,
        )

        # Step 2: Find the best supplier for this quantity
        selected_supplier = self.rank_suppliers(
            suppliers=request.available_suppliers,
            quantity=reorder_quantity,
        )

        # Step 3: Calculate estimated total cost
        if selected_supplier is not None and reorder_quantity > 0:
            # Total cost = (unit cost * quantity) + fixed transport cost
            unit_cost_total = selected_supplier.unit_cost * reorder_quantity
            estimated_total_cost = unit_cost_total + selected_supplier.transport_cost

            # Generate decision rationale
            decision_rationale = (
                f"Supplier {selected_supplier.supplier_id} chosen due to optimal "
                f"reliability-to-cost ratio (score: {selected_supplier.reliability_score}). "
                f"Total cost: ${estimated_total_cost:.2f} for {reorder_quantity} units."
            )
        else:
            # No order needed or no supplier available
            estimated_total_cost = 0.0
            decision_rationale = (
                "No reorder required. Current inventory meets predicted demand targets."
                if reorder_quantity == 0
                else "No suitable suppliers available for this order."
            )

        # Step 4: Build and return the response
        response = ProcurementDecisionResponse(
            sku_id=request.sku_id,
            reorder_quantity=reorder_quantity,
            selected_supplier_id=(
                selected_supplier.supplier_id if selected_supplier else None
            ),
            estimated_total_cost=estimated_total_cost,
            decision_rationale=decision_rationale,
        )

        logger.info(
            f"Procurement optimization complete for SKU {request.sku_id}: "
            f"quantity={reorder_quantity}, "
            f"supplier={response.selected_supplier_id}, "
            f"cost=${estimated_total_cost:.2f}"
        )

        return response
