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
