"""SQLAlchemy ORM Models for Warehouse Topology & Movement Telemetry.

Defines the mapping between Python objects and the underlying PostgreSQL/TimescaleDB tables.
These models extend the core Base from the parent infrastructure models module.

Domain-Driven Design context:
- Warehouse topology (nodes + edges) forms a directed graph stored relationally.
- Movement telemetry is time-series data stored in a TimescaleDB hypertable
  for efficient temporal queries and aggregation.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.infrastructure.models import Base


class AuditLedger(Base):
    """Immutable audit ledger for tracking financial and inventory events.

    Domain-Driven Design context:
    - Every INVOICE_SUBMITTED, INVENTORY_OVERRIDE, SHIPMENT_RECEIVED,
      or SUPPLIER_PRICE_CHANGE event is recorded here for fraud analysis.
    - The corresponding PostgreSQL trigger 'prevent_audit_tampering()'
      blocks any UPDATE or DELETE operations on this table, enforcing immutability.
    - Timestamps use server_default to guarantee record integrity at the DB level.

    Attributes:
        id: UUID primary key generated at the application layer.
        timestamp: When the event occurred (server default, immutable).
        event_type: The event category (e.g., 'invoice_submitted').
        entity_id: Supplier or user ID responsible for the event.
        sku_id: Optional SKU involved in the event.
        amount_value: Optional monetary or quantity value.
        event_metadata: JSONB field for additional flexible context.
    """

    __tablename__ = "audit_ledger"

    id = Column(String(255), primary_key=True)
    timestamp = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    event_type = Column(String(100), nullable=False)
    entity_id = Column(String(255), nullable=False)
    sku_id = Column(String(255), nullable=True)
    amount_value = Column(Float, nullable=True)
    event_metadata = Column(JSONB, nullable=True)


class AuditAnomalyScore(Base):
    """Stores the fraud/anomaly scoring results for audit ledger events.

    Domain-Driven Design context:
    - Anomaly scores are written to a SEPARATE table (not updating audit_ledger)
      to maintain the immutability guarantee of the ledger.
    - The event_id is both a primary key and a foreign key pointing to audit_ledger.
    - Scores are generated asynchronously by the Celery worker.

    Attributes:
        event_id: Primary key and foreign key referencing audit_ledger(id).
        risk_score: Normalized probability that the event is fraudulent (0.0 to 1.0).
        is_flagged: Whether the event exceeded the risk threshold.
        reason: Human-readable explanation of the score.
        timestamp: When the scoring analysis was completed.
    """

    __tablename__ = "audit_anomaly_scores"

    event_id = Column(
        String(255),
        ForeignKey("audit_ledger.id"),
        primary_key=True,
        nullable=False,
    )
    risk_score = Column(Float, nullable=False)
    is_flagged = Column(Boolean, nullable=False, default=False)
    reason = Column(String(500), nullable=True)
    timestamp = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class LoRAAdapterRegistry(Base):
    """Registers and tracks LoRA fine-tuning adapters for prediction modules.

    Domain-Driven Design context:
    - Each row represents a fine-tuning attempt for a specific module.
    - Status transitions: TRAINING -> VALIDATING -> ACTIVE (or FAILED).
    - The orchestrator uses this table to decide whether to inject a LoRA
      adapter or fall back to the base model during inference.
    - Active adapters are hot-swapped into the prediction pipeline.

    Attributes:
        id: UUID primary key generated at the application layer.
        module_name: The target module name (e.g., 'demand_forecast').
        base_model_version: The base model version this adapter was trained from.
        adapter_weights_path: File path to the stored LoRA adapter weights.
        status: Current lifecycle stage: TRAINING, VALIDATING, ACTIVE, or FAILED.
        created_at: When this adapter training was initiated.
    """

    __tablename__ = "lora_adapter_registry"

    id = Column(String(255), primary_key=True)
    module_name = Column(String(100), nullable=False, index=True)
    supplier_id = Column(String(255), nullable=True, index=True)
    base_model_version = Column(String(100), nullable=False)
    adapter_weights_path = Column(String(500), nullable=True)
    checksum = Column(String(255), nullable=True)
    status = Column(String(50), nullable=False, default="TRAINING")
    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class AssetTelemetryModel(Base):
    """Time-series telemetry for predictive maintenance assets."""

    __tablename__ = "asset_telemetry"

    recorded_at = Column(DateTime(timezone=True), primary_key=True, nullable=False)
    asset_id = Column(String(255), primary_key=True, nullable=False)
    equipment_age_days = Column(Integer, nullable=False)
    vibration_index = Column(Float, nullable=False)


class RouteTelemetryModel(Base):
    """Time-series telemetry for fuel cost / shipping routes."""

    __tablename__ = "route_telemetry"

    recorded_at = Column(DateTime(timezone=True), primary_key=True, nullable=False)
    route_id = Column(String(255), primary_key=True, nullable=False)
    route_distance_km = Column(Float, nullable=False)
    vehicle_efficiency = Column(Float, nullable=False)
