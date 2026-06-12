"""SQLAlchemy ORM Models for Database Persistence.

Defines the mapping between Python objects and the underlying PostgreSQL/TimescaleDB tables.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class SupplierModel(Base):
    """Represents the 'suppliers' table containing static and polymorphic metadata.

    Attributes:
        supplier_id: Primary key identifier for the supplier.
        system_origin: The origin system (e.g., TALLY_XML, SAP_ODATA).
        industry_vertical: The industry vertical (e.g., GROCERY, HEAVY_GOODS).
        industry_specific_metadata: JSONB field for polymorphic industry-specific data.
        created_at: Timestamp when the record was created.
        telemetry_records: Relationship to telemetry data.
    """

    __tablename__ = "suppliers"

    supplier_id = Column(String(255), primary_key=True, index=True)
    system_origin = Column(String(100), nullable=False)
    industry_vertical = Column(String(100), nullable=False)
    industry_specific_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))

    telemetry_records = relationship("TelemetryModel", back_populates="supplier")


class TelemetryModel(Base):
    """Represents the 'inventory_telemetry' TimescaleDB hypertable.

    Attributes:
        recorded_at: Timestamp of the telemetry record.
        supplier_id: Foreign key to suppliers table.
        tracking_id: Unique identifier linking to the ML prediction log.
        inventory_count: Current inventory count (must be >= 0).
        delivery_delay_days: Delivery delay in days (must be >= 0).
        predicted_stockout_probability: ML-predicted probability of stockout.
        is_critical_risk: Boolean flag for critical risk threshold.
        supplier: Relationship back to supplier.
    """

    __tablename__ = "inventory_telemetry"

    recorded_at = Column(DateTime(timezone=True), primary_key=True, nullable=False)
    supplier_id = Column(
        String(255),
        ForeignKey("suppliers.supplier_id"),
        primary_key=True,
        nullable=False,
    )
    tracking_id = Column(String(255), index=True, nullable=True)
    sku_id = Column(String(255), index=True, nullable=True)
    tenant_id = Column(String(255), index=True, nullable=True)
    inventory_count = Column(Integer, nullable=False)
    delivery_delay_days = Column(Integer, nullable=False)
    predicted_stockout_probability = Column(Float, nullable=True)
    is_critical_risk = Column(Boolean, nullable=True)

    supplier = relationship("SupplierModel", back_populates="telemetry_records")


class MLPredictionLog(Base):
    """Represents the 'ml_prediction_log' table for tracking ML predictions.

    This table stores raw ML predictions before they are joined with actuals.
    Enables Population Stability Index (PSI) calculation by comparing
    predicted distributions against actual ground truth.

    Attributes:
        id: Auto-incrementing primary key.
        tracking_id: Unique identifier linking prediction to telemetry actuals.
        predicted_stockout_probability: The ML model's predicted probability.
        predicted_at: Timestamp when the prediction was generated.
    """

    __tablename__ = "ml_prediction_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tracking_id = Column(String(255), index=True, nullable=False)
    predicted_stockout_probability = Column(Float, nullable=False)
    predicted_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
