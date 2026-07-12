"""Domain schemas for Sentinel-Flow MVP.

These models enforce strict data validation before any processing occurs.
"""

import math
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# -------------------------------------------------------------------
# Recursion guard constants and helper
# -------------------------------------------------------------------
MAX_DICT_DEPTH: int = 5


def check_dict_depth(d: dict, current_depth: int = 1) -> int:
    """Recursively calculates the maximum depth of a dictionary.

    Raises ValueError if the depth exceeds MAX_DICT_DEPTH, which
    prevents deeply nested JSON payloads from reaching Celery
    serialization (where they would trigger a RecursionError).
    """
    if current_depth > MAX_DICT_DEPTH:
        raise ValueError(
            f"Payload exceeds maximum allowed nested depth of {MAX_DICT_DEPTH}"
        )

    max_depth = current_depth
    for value in d.values():
        if isinstance(value, dict):
            depth = check_dict_depth(value, current_depth + 1)
            if depth > max_depth:
                max_depth = depth
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    depth = check_dict_depth(item, current_depth + 1)
                    if depth > max_depth:
                        max_depth = depth
    return max_depth


# -------------------------------------------------------------------
# ComputeHypervisor routing decision constants
# These string constants define the three possible routing paths that
# the hypervisor can choose for a given inference request.
# -------------------------------------------------------------------
ROUTE_BASE_MODEL: str = "BASE_MODEL"
ROUTE_LORA_MODEL: str = "LORA_MODEL"
ROUTE_HEURISTIC_FALLBACK: str = "HEURISTIC_FALLBACK"


class SupplierRecord(BaseModel):
    """Represents a single parsed record from a supplier's raw data dump (e.g., Tally XML).

    Attributes:
        supplier_id: The unique identification string for the supplier.
        timestamp: The exact date and time the record was created.
        delivery_delay_days: Number of days the previous shipment was delayed.
        contact_name: Optional name of the contact person at the supplier.
        contact_email: Optional email address of the contact person.
    """

    supplier_id: str = Field(
        ...,
        description="The unique identification string for the supplier.",
    )

    timestamp: datetime = Field(
        ...,
        description="The exact date and time the record was created.",
    )

    delivery_delay_days: int = Field(
        ...,
        ge=0,
        description="Number of days the previous shipment was delayed.",
    )

    contact_name: Optional[str] = Field(
        default=None,
        description="Optional name of the contact person at the supplier.",
    )

    contact_email: Optional[str] = Field(
        default=None,
        description="Optional email address of the contact person.",
    )


class BatchIngestionRequest(BaseModel):
    """The standardized contract for batch data ingestion.

    Attributes:
        batch_identifier: Unique UUID for tracking this specific batch of data.
        source_system: Origin system name (e.g., 'TALLY_XML', 'SAP_ODATA').
        records: List of supplier telemetry records. Must not be empty.
        originating_region: Geographic region for compliance routing
                            (e.g., 'EU', 'IN', 'DEFAULT').
    """

    batch_identifier: str = Field(
        ...,
        description="Unique UUID for tracking this specific batch of data.",
    )

    source_system: str = Field(
        ...,
        description="Origin system name (e.g., 'TALLY_XML', 'SAP_ODATA').",
    )

    records: List[SupplierRecord] = Field(
        ...,
        min_length=1,
        description="List of supplier telemetry records. Must not be empty.",
    )

    originating_region: str = Field(
        default="DEFAULT",
        description="Geographic region for compliance routing (e.g., 'EU', 'IN', 'DEFAULT').",
    )

    # Constraint guard: reject NaN or Infinity on any float field
    @field_validator("records")
    @classmethod
    def validate_records_not_empty_and_finite(
        cls, record_list: List[SupplierRecord]
    ) -> List[SupplierRecord]:
        if not record_list:
            raise ValueError("records list must not be empty.")
        for idx, record in enumerate(record_list):
            for field_name, field_value in record.__dict__.items():
                if isinstance(field_value, float) and not math.isfinite(field_value):
                    raise ValueError(
                        f"records[{idx}].{field_name} is not finite "
                        f"(received {field_value!r})."
                    )
        return record_list


class PredictionResponse(BaseModel):
    """The output contract from the ML Serving layer, intercepted by Aegis Lite.

    Attributes:
        tracking_id: Unique identifier linking prediction to actual telemetry.
        supplier_id: The unique identification string for the supplier.
        predicted_stockout_probability: Percentage chance of running out of stock (0.0 to 1.0).
        is_critical_risk: Boolean flag set to True if probability exceeds safety thresholds.
        compliance_region: The region dictating data routing, for example, 'INDIA_DPDP'.
    """

    tracking_id: str = Field(
        ...,
        description="Unique identifier linking prediction to actual telemetry.",
    )

    supplier_id: str = Field(
        ...,
        description="The unique identification string for the supplier.",
    )

    predicted_stockout_probability: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Percentage chance of running out of stock (0.0 to 1.0).",
    )

    is_critical_risk: bool = Field(
        ...,
        description="Boolean flag set to True if probability exceeds safety thresholds.",
    )

    compliance_region: str = Field(
        ...,
        description="The region dictating data routing, for example, 'INDIA_DPDP'.",
    )

    # Constraint guard: reject NaN or Infinity on the predicted probability
    @field_validator("predicted_stockout_probability")
    @classmethod
    def validate_prediction_is_finite(cls, probability_value: float) -> float:
        if not math.isfinite(probability_value):
            raise ValueError(
                f"predicted_stockout_probability must be finite "
                f"(received {probability_value!r})."
            )
        return probability_value


class BaseInferenceRequest(BaseModel):
    """Standardized input contract for all intelligence module predictions.

    This schema ensures every prediction request carries the necessary
    metadata for distributed tracing, module routing, and timeout enforcement.

    Phase 4.1 addition: The hypervisor fields (client_id, sla_tier,
    compute_budget_remaining) allow the ComputeHypervisor to make
    cost-aware routing decisions before any model inference begins.

    Attributes:
        correlation_id: Unique UUID for distributed tracing across services.
        module_id: Target model identifier (e.g., 'demand_forecast', 'fuel_cost').
        features: Dictionary containing the input feature vector for the model.
        timeout_ms: Maximum allowed execution time in milliseconds.
        client_id: Identifies the calling client for per-client budget tracking.
        sla_tier: Service level agreement tier that determines routing priority.
        compute_budget_remaining: Remaining compute budget for this client.
    """

    correlation_id: UUID = Field(
        default_factory=uuid4,
        description="Unique UUID for distributed tracing across services.",
    )

    # ------------------------------------------------------------------
    # Context Identifiers
    # At least one of these should be provided based on the target module.
    # ------------------------------------------------------------------

    supplier_id: Optional[str] = Field(
        default=None,
        description="Supplier identifier (used for demand forecast / stockout).",
    )

    sku_id: Optional[str] = Field(
        default=None,
        description="Optional SKU identifier for demand forecast.",
    )

    asset_id: Optional[str] = Field(
        default=None,
        description="Asset identifier (used for predictive maintenance).",
    )

    route_id: Optional[str] = Field(
        default=None,
        description="Route identifier (used for fuel cost / logistics).",
    )

    module_id: str = Field(
        ...,
        description="Target model identifier (e.g., 'demand_forecast', 'fuel_cost').",
    )

    covariates: Dict[str, float] | None = Field(
        default=None, 
        description="Exogenous variables like weather or trends"
    )

    features: Dict[str, Any] = Field(
        ...,
        description="Dictionary containing the input feature vector for the model.",
    )

    @field_validator("features", mode="before")
    @classmethod
    def validate_features_depth(cls, v: Any) -> Any:
        """Validate that the features dict does not exceed the max depth.

        This prevents deeply nested JSON payloads from reaching Celery
        serialization, where they would trigger a RecursionError.
        """
        if isinstance(v, dict):
            check_dict_depth(v)
        return v

    timeout_ms: int = Field(
        default=500,
        description="Maximum allowed execution time in milliseconds.",
    )

    # ------------------------------------------------------------------
    # Phase 4.1 — ComputeHypervisor Fields
    # These fields are used by the hypervisor to decide which model
    # path to route each request through. All have safe defaults so
    # that legacy callers that do not send these fields still work.
    # ------------------------------------------------------------------

    client_id: str = Field(
        default="anonymous_default",
        description="Identifies the calling client for per-client budget tracking.",
    )

    sla_tier: str = Field(
        default="basic",
        description=(
            "Service level agreement tier. "
            "Must be one of: 'premium', 'standard', 'basic'."
        ),
    )

    compute_budget_remaining: float = Field(
        default=100.0,
        description="Remaining compute budget for this client.",
    )

    # ------------------------------------------------------------------
    # Pydantic validator: sla_tier
    # We convert the input to lowercase so that callers sending
    # "PREMIUM" or "Premium" are handled gracefully. If the value
    # is not one of the three recognized tiers, we raise a clear error.
    # ------------------------------------------------------------------
    @field_validator("sla_tier")
    @classmethod
    def validate_sla_tier_to_lowercase(cls, sla_tier_value: str) -> str:
        """Convert sla_tier to lowercase and validate it is a known tier.

        Args:
            sla_tier_value: The raw sla_tier string from the incoming request.

        Returns:
            The sanitized lowercase sla_tier string.

        Raises:
            ValueError: If sla_tier is not one of 'premium', 'standard', 'basic'.
        """
        # Convert the input to lowercase to handle case variations
        sanitized_tier = sla_tier_value.lower()

        # Define the set of allowed SLA tiers
        allowed_tiers = ["premium", "standard", "basic"]

        # If the sanitized value is not in the allowed list, raise an error
        if sanitized_tier not in allowed_tiers:
            raise ValueError(
                f"sla_tier must be one of {allowed_tiers}. "
                f"Received: '{sla_tier_value}'."
            )

        # Return the sanitized lowercase tier
        return sanitized_tier

    @model_validator(mode='after')
    def validate_context_identifier(self) -> 'BaseInferenceRequest':
        """Ensure at least one context identifier is provided or can be extracted.

        Checks if supplier_id, asset_id, or route_id are present, or falls back
        to client_id if applicable.
        """
        # We can optionally also check inside features if they are passed there
        has_context = any([
            self.supplier_id,
            self.asset_id,
            self.route_id,
            self.features.get("supplier_id"),
            self.features.get("asset_id"),
            self.features.get("route_id"),
            self.client_id != "anonymous_default",
        ])
        
        if not has_context:
            raise ValueError(
                "InferenceRequest must include at least one contextual identifier: "
                "supplier_id, asset_id, or route_id."
            )
        return self


class StandardizedPredictionResponse(BaseModel):
    """Standardized output contract for all intelligence module predictions.

    This schema guarantees a consistent response structure regardless of
    which model or fallback heuristic generated the prediction.
    """

    correlation_id: UUID = Field(
        ...,
        description="Matches the correlation_id from the original request.",
    )

    prediction_value: float = Field(
        ...,
        description="The primary numeric output of the model (e.g., units, probability).",
    )

    confidence_score: float = Field(
        ...,
        description="Confidence score between 0.0 and 1.0.",
        ge=0.0,
        le=1.0,
    )

    fallback_engaged: bool = Field(
        ...,
        description="True if the primary model failed and the heuristic was used.",
    )

    model_version: str = Field(
        ...,
        description="Identifier of the specific model or heuristic version used.",
    )

    historical_trajectory: List[float] = Field(
        default_factory=list,
        description="The historical data points trailing up to the prediction.",
    )

    forecast_trajectory: List[float] = Field(
        default_factory=list,
        description="The multi-step prediction trajectory generated by the model.",
    )

    execution_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Diagnostic telemetry and execution timing for the prediction.",
    )


class HardwareInferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str
    supplier_id: str
    sku_id: str
    route_id: str
    compute_budget: float = 50.0
    current_inventory: Optional[int] = None
    lead_time_days: Optional[int] = None


class SupplierOption(BaseModel):
    """Data contract representing a potential supplier for procurement.

    Attributes:
        supplier_id: Unique identifier for the supplier.
        reliability_score: Trust score from 0.0 to 1.0 (output from Phase 2.1 monitoring).
        unit_cost: Cost per unit of the item.
        transport_cost: Fixed transport/shipping cost for the order.
        lead_time_days: Number of days until delivery.
    """

    supplier_id: str = Field(
        ...,
        description="Unique identifier for the supplier.",
    )

    reliability_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Trust score from 0.0 to 1.0 (output from Phase 2.1 monitoring).",
    )

    unit_cost: float = Field(
        ...,
        ge=0.0,
        description="Cost per unit of the item.",
    )

    transport_cost: float = Field(
        ...,
        ge=0.0,
        description="Fixed transport/shipping cost for the order.",
    )

    lead_time_days: int = Field(
        ...,
        ge=0,
        description="Number of days until delivery.",
    )


class ProcurementOptimizationRequest(BaseModel):
    """Input contract for the procurement optimization engine.

    Attributes:
        sku_id: Stock keeping unit identifier for the item.
        current_inventory: Current stock level in the warehouse.
        predicted_demand: Forecasted demand from Phase 2.2 demand forecast.
        warehouse_capacity: Maximum storage capacity of the warehouse.
        available_suppliers: List of potential suppliers to evaluate.
    """

    sku_id: str = Field(
        ...,
        description="Stock keeping unit identifier for the item.",
    )

    current_inventory: int = Field(
        ...,
        ge=0,
        description="Current stock level in the warehouse.",
    )

    predicted_demand: int = Field(
        ...,
        ge=0,
        description="Forecasted demand from Phase 2.2 demand forecast.",
    )

    warehouse_capacity: int = Field(
        ...,
        ge=0,
        description="Maximum storage capacity of the warehouse.",
    )

    available_suppliers: List[SupplierOption] = Field(
        ...,
        description="List of potential suppliers to evaluate.",
    )


class ProcurementDecisionResponse(BaseModel):
    """Output contract containing the optimized procurement decision.

    Attributes:
        sku_id: The stock keeping unit identifier.
        reorder_quantity: Calculated optimal quantity to order.
        selected_supplier_id: ID of the chosen supplier (null if quantity is 0).
        estimated_total_cost: Total cost including units and transport.
        decision_rationale: Human-readable explanation of the decision.
    """

    sku_id: str = Field(
        ...,
        description="The stock keeping unit identifier.",
    )

    reorder_quantity: int = Field(
        ...,
        ge=0,
        description="Calculated optimal quantity to order.",
    )

    selected_supplier_id: Optional[str] = Field(
        default=None,
        description="ID of the chosen supplier (null if quantity is 0).",
    )

    estimated_total_cost: float = Field(
        ...,
        ge=0.0,
        description="Total cost including units and transport.",
    )

    decision_rationale: str = Field(
        ...,
        description="Human-readable explanation of the decision.",
    )


class AuditEventType(str, Enum):
    """Enumeration of auditable event types for the immutable ledger.

    Domain-Driven Design context:
    - Every financial or inventory change must be recorded immutably.
    - Enum values represent the bounded context of each event (finance, inventory, supplier).
    """
    INVOICE_SUBMITTED = "invoice_submitted"
    INVENTORY_OVERRIDE = "inventory_override"
    SHIPMENT_RECEIVED = "shipment_received"
    SUPPLIER_PRICE_CHANGE = "supplier_price_change"


class AuditEventPayload(BaseModel):
    """Payload contract for ingesting an auditable event into the immutable ledger.

    IDEMPOTENCY RULE (Financial Events):
    For INVOICE_SUBMITTED and SUPPLIER_PRICE_CHANGE events, you MUST include
    a 'transaction_id' key in the 'metadata' dictionary. This value is used
    by a database-level unique index to prevent duplicate submissions.
    Example: {"metadata": {"transaction_id": "INV-2024-001", ...}}

    Attributes:
        event_type: The category of the event being recorded.
        entity_id: The supplier or user ID responsible for the event.
        sku_id: Optional SKU involved in the event.
        amount_value: Optional monetary or quantity value.
        metadata: Additional flexible context for the event. Include
                  'transaction_id' for deduplication of financial events.
    """

    event_type: AuditEventType = Field(
        ...,
        description="The category of the event being recorded.",
    )

    entity_id: str = Field(
        ...,
        description="The supplier or user ID responsible for the event.",
    )

    sku_id: Optional[str] = Field(
        default=None,
        description="Optional SKU involved in the event.",
    )

    amount_value: Optional[float] = Field(
        default=None,
        description="Optional monetary or quantity value.",
    )

    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional flexible context for the event.",
    )


class AnomalyScoreResponse(BaseModel):
    """Output contract for fraud/anomaly scoring.

    Attributes:
        event_id: The unique identifier of the scored event.
        risk_score: Probability that the event is fraudulent (0.0 to 1.0).
        is_flagged: Whether the event exceeds the risk threshold.
        reason: Human-readable explanation of the score, if flagged.
    """

    event_id: str = Field(
        ...,
        description="The unique identifier of the scored event.",
    )

    risk_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Probability that the event is fraudulent (0.0 to 1.0).",
    )

    is_flagged: bool = Field(
        ...,
        description="Whether the event exceeds the risk threshold.",
    )

    reason: Optional[str] = Field(
        default=None,
        description="Human-readable explanation of the score, if flagged.",
    )


class EdgeNodeStatus(str, Enum):
    """Enumerates the health/trust states of a supplier edge node.

    Domain-Driven Design context:
    - Edge nodes operate in zero-trust environments.
    - ONLINE: node is actively participating in the current round.
    - OFFLINE: node did not submit weights for the current round.
    - DEGRADED: node submitted weights but they were partially anomalous.
    - QUARANTINED: node has been permanently banned due to repeated poisoning.
    """
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    QUARANTINED = "quarantined"


class FederatedWeightPayload(BaseModel):
    """The standardized ingress contract for a single edge node's weight update.

    Every supplier edge node submits its local model gradients as a flattened
    list of floats. A cryptographic signature is optional for future rounds
    when identity verification is enforced.

    Attributes:
        supplier_id: Unique identifier for the supplier edge node.
        round_number: The federated learning round this update belongs to.
        weights: Flattened 1-D list of model gradients/weights.
                 Rejected if any element is NaN or Infinity.
        signature: Optional cryptographic signature for node identity verification.
    """

    supplier_id: str = Field(
        ...,
        description="Unique identifier for the supplier edge node.",
    )

    round_number: int = Field(
        ...,
        ge=1,
        description="The federated learning round this update belongs to.",
    )

    weights: List[float] = Field(
        ...,
        min_length=1,
        description="Flattened 1-D list of model gradients/weights.",
    )

    signature: Optional[str] = Field(
        default=None,
        description="Optional cryptographic signature for node identity verification.",
    )

    @field_validator("weights")
    @classmethod
    def validate_weights_are_finite(cls, weight_values: List[float]) -> List[float]:
        """Reject any weight array that contains NaN or Infinity.

        Poisoned updates often inject NaN or Inf values to destabilize the
        global model. This validator catches those before they reach the
        mathematical aggregation layer.

        Args:
            weight_values: The raw weight list from the edge node.

        Returns:
            The validated weight list if all values are finite.

        Raises:
            ValueError: If any weight is NaN, Infinity, or -Infinity.
        """
        for index, single_weight in enumerate(weight_values):
            if not math.isfinite(single_weight):
                raise ValueError(
                    f"Weight at index {index} is not finite "
                    f"(received {single_weight!r}). "
                    f"NaN and Infinity are not permitted in weight updates."
                )
        return weight_values


class AdapterRegistryResponse(BaseModel):
    """Schema for returning LoRA adapter registry records."""
    id: str
    module_name: str
    supplier_id: Optional[str] = None
    base_model_version: str
    adapter_weights_path: Optional[str] = None
    checksum: Optional[str] = None
    status: str
    created_at: datetime


# --- Risk Dashboard Domain Models ---
# These Pydantic schemas strictly define the shape of the data
# sent to the frontend Global Risk Matrix. Every field is typed
# and validated so the UI never receives unexpected data.

class RiskItem(BaseModel):
    """Represents a single risk event in the supply chain.

    Each item maps to one row in the frontend risk card.
    - supplier_id: The name or ID of the flagged supplier.
    - metric: A short description of what triggered the alert.
    - value: A human-readable measurement (units, days, percentage).
    - severity: Controls the color coding: 'critical' = red, 'warning' = amber, 'info' = blue.
    """
    supplier_id: str = Field(..., description="The ID of the supplier or SKU")
    metric: str = Field(..., description="The type of risk (e.g., 'Stockout Probability', 'Delivery Delay')")
    value: str = Field(..., description="The human-readable value (e.g., '95%', '15 days')")
    severity: str = Field(..., description="Risk level: 'critical', 'warning', or 'info'")


class RiskDashboardResponse(BaseModel):
    """The complete payload for the Global Risk Matrix frontend component.

    Contains three separate lists — one for each risk category.
    Each list holds zero or more RiskItem objects. Empty lists
    are valid (the UI will show '0 flagged suppliers' for that card).
    """
    stockouts: List[RiskItem] = Field(default_factory=list, description="Impending stockout alerts")
    dead_stock: List[RiskItem] = Field(default_factory=list, description="Dead / stagnant inventory alerts")
    anomalies: List[RiskItem] = Field(default_factory=list, description="Anomalous delivery + risk alerts")


# --- Phase 13.1: Pharmacological Ledger Schemas ---

class MedicationSchema(BaseModel):
    """
    Data contract for creating or reading a medication.
    """
    sku_id: str = Field(..., description="Unique identifier for the medication")
    apis: List[str] = Field(..., description="List of Active Pharmaceutical Ingredients")
    therapeutic_classes: List[str] = Field(..., description="List of therapeutic classes")
    cdsco_schedule: str = Field(..., description="Regulatory schedule (e.g., Schedule H)")

class PatientSchema(BaseModel):
    """
    Data contract for patient demographics and chronic diseases.
    """
    patient_id: str
    age: int = Field(..., ge=0, le=120)
    gender: str
    chronic_diseases: List[str] = []

class MedicationBatchSchema(BaseModel):
    """
    Data contract for a specific batch of medication.
    Beginner Note: We use strict types like 'date' and 'float' to ensure data integrity
    before it ever reaches the database.
    """
    batch_id: str
    sku_id: str
    expiry_date: date
    cost_price: float = Field(..., ge=0.0)
    max_retail_price: float = Field(..., ge=0.0)
    available_quantity: int = Field(..., ge=0)
    shelf_location: str = Field(default="UNASSIGNED", description="Physical shelf or bin location")

# --- Phase 13.2: Event-Driven POS Schemas ---

class MedicationSoldEvent(BaseModel):
    """
    Data contract for a Point-of-Sale (POS) transaction.
    Beginner Note: This is the exact payload that gets published to Kafka 
    when a pharmacist scans a medicine at the register.
    """
    transaction_id: str = Field(..., description="Unique ID from the POS register")
    batch_id: str = Field(..., description="The specific physical batch sold")
    sku_id: str = Field(..., description="The medication identifier")
    quantity_sold: int = Field(..., gt=0, description="Number of units sold")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    pharmacy_location: str = Field(..., description="Store or hospital ID")

# --- Phase 14.3: Distributor Scorecard Schemas ---

class DistributorScorecardResponse(BaseModel):
    """
    The financial scorecard returned to the frontend dashboard.
    """
    supplier_id: str
    total_orders_analyzed: int
    on_time_delivery_rate: float = Field(..., description="Percentage of orders delivered on time")
    total_shortfall_items: int = Field(..., description="Total units the distributor failed to deliver")
    financial_loss_rupees: float = Field(..., description="Total profit lost due to shortfalls (in ₹)")
    recommendation: str = Field(..., description="AI-generated negotiation advice")

class KnowledgeIngestionRequest(BaseModel):
    """Contract for ingesting new clinical guidelines."""
    sku_id: str = Field(..., description="The Medication SKU ID")
    content: str = Field(..., description="The clinical text to embed (e.g., 'Take with food')")
    metadata_payload: Optional[Dict[str, Any]] = Field(default={}, description="Optional metadata like source URL")

class KnowledgeIngestionResponse(BaseModel):
    """Response contract for ingestion."""
    message: str
    task_id: str

class SemanticSearchRequest(BaseModel):
    """Contract for querying the clinical knowledge base."""
    query: str = Field(..., description="The pharmacist's question (e.g., 'Safe for pregnancy?')")
    sku_id: Optional[str] = Field(None, description="Optional: Filter by specific medication SKU")
    top_k: int = Field(3, description="Number of results to return")

class SearchResultItem(BaseModel):
    """A single matched clinical guideline."""
    sku_id: str
    content: str
    confidence_score: float
    metadata_payload: dict

class SemanticSearchResponse(BaseModel):
    """Response contract for semantic search."""
    query: str
    results: list[SearchResultItem]
    safety_warning: Optional[str] = None

class RAGQueryRequest(BaseModel):
    """Contract for asking the AI assistant a clinical question."""
    query: str = Field(..., description="The natural language question (e.g., 'Is this safe for a 34F pregnant patient?')")
    sku_id: Optional[str] = Field(None, description="Optional: Filter context by specific medication SKU")

class RAGQueryResponse(BaseModel):
    """Response contract for the AI assistant."""
    query: str
    answer: str = Field(..., description="The AI-generated answer based strictly on context.")
    context_used: list[SearchResultItem] = Field(..., description="The exact database records used to generate the answer.")


# --- Phase 9: Cross-Model Hybrid Substitute Schemas ---
# Beginner Note: These schemas define the contract for our "Substitute Finder"
# feature. When a pharmacist scans a medicine that is out of stock, we use
# AI-powered vector similarity to find chemically equivalent alternatives
# that we DO have in stock.

class SubstituteRequestSchema(BaseModel):
    """Contract for requesting substitute recommendations.

    A pharmacist sends us the SKU of the medicine they CANNOT dispense,
    and we find the closest chemical alternatives that ARE in stock.

    Attributes:
        target_sku: The SKU ID of the medication the pharmacist wants to substitute.
        threshold: Minimum similarity score (0.0 to 1.0). Default 0.80 means
                   we only show substitutes that are at least 80% chemically similar.
                   A junior pharmacist can lower this threshold (e.g., 0.70) if
                   the patient is willing to accept a less precise match.
    """
    target_sku: str = Field(
        ...,
        description="The SKU of the medication we need to find a substitute for",
    )
    threshold: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
        description="Minimum vector similarity threshold (0.0 to 1.0, default 0.80)",
    )


class SubstituteItemSchema(BaseModel):
    """A single substitute recommendation with pricing and stock info.

    Beginner Note: This is what we show the pharmacist on the screen.
    It combines AI-powered similarity (matching_score) with real-world
    inventory data (stock_qty, unit_price_inr) so they can make an
    informed decision about which substitute to offer the patient.

    Attributes:
        sku_id: The SKU ID of the substitute medication.
        brand_name: The brand name (e.g., 'Pan 40').
        generic_class: The generic/chemical name (e.g., 'Pantoprazole').
        matching_score: How chemically similar the substitute is (0.0 to 1.0).
        stock_qty: How many units we physically have across all batches.
        unit_price_inr: The cheapest price across all batches (in Indian Rupees).
    """
    sku_id: str = Field(
        ...,
        description="The substitute SKU identifier",
    )
    brand_name: str = Field(
        ...,
        description="Brand name of the substitute (e.g., 'Pan 40')",
    )
    generic_class: str = Field(
        ...,
        description="Generic/chemical name (e.g., 'Pantoprazole')",
    )
    matching_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Vector similarity score — how chemically close this substitute is",
    )
    stock_qty: int = Field(
        ...,
        ge=0,
        description="Total available stock across all batches of this SKU",
    )
    unit_price_inr: float = Field(
        ...,
        ge=0.0,
        description="Lowest retail price across all batches (in INR)",
    )


class SubstituteResponseSchema(BaseModel):
    """Contract for the substitute finder response.

    Attributes:
        status: Always 'success' on a valid request (even if no substitutes found).
        original_sku: The SKU the pharmacist originally asked about.
        substitutes: List of substitute candidates sorted by price (cheapest first).
    """
    status: str = Field(
        default="success",
        description="Response status indicator",
    )
    original_sku: str = Field(
        ...,
        description="The original SKU the pharmacist requested substitutes for",
    )
    substitutes: List[SubstituteItemSchema] = Field(
        default_factory=list,
        description="List of substitute recommendations, sorted by price ascending",
    )


class PatientCreate(BaseModel):
    patient_id: str
    tenant_id: str = Field(default="system_admin")
    name: str
    phone_number: str
    age: Optional[int] = None
    gender: Optional[str] = None
    chronic_diseases: List[str] = []


class TreatmentPlanCreate(BaseModel):
    patient_id: str
    tenant_id: str = Field(default="system_admin")
    sku_id: str
    daily_dosage: float = Field(..., gt=0, description="Pills/units consumed per day")
    total_quantity_dispensed: int = Field(..., gt=0, description="Total pills/units given")


class TreatmentPlanResponse(BaseModel):
    plan_id: str
    patient_id: str
    sku_id: str
    daily_dosage: float
    total_quantity_dispensed: int
    start_date: datetime
    projected_depletion_date: datetime
    is_active: bool

class TenantSettingsUpdate(BaseModel):
    upi_id: Optional[str] = None
    meta_whatsapp_token: Optional[str] = None
    whatsapp_phone_id: Optional[str] = None

class TenantSettingsResponse(BaseModel):
    tenant_id: str
    name: str
    upi_id: Optional[str]
    meta_whatsapp_token_configured: bool
    whatsapp_phone_id: Optional[str]
