"""SQLAlchemy ORM Models for Database Persistence.

Defines the mapping between Python objects and the underlying PostgreSQL/TimescaleDB tables.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Date, Index, Numeric, text
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
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


# --- Phase 13.1: Pharmacological Ledger Models ---

class MedicationModel(Base):
    """
    Represents a specific medication (SKU) in the system.
    Beginner Note: This acts as the 'anchor' for our batches. We store the active ingredients
    and regulatory rules (like CDSCO Schedule H/H1) here.
    """
    __tablename__ = "medications"

    # We use sku_id as the primary key because it uniquely identifies the product type
    sku_id = Column(String, primary_key=True, index=True)
    
    # ARRAY allows us to store multiple ingredients or classes in a single column
    apis = Column(ARRAY(String), nullable=False) # Active Pharmaceutical Ingredients
    therapeutic_classes = Column(ARRAY(String), nullable=False)
    
    # Regulatory scheduling (e.g., 'Schedule H', 'Schedule H1', 'OTC')
    cdsco_schedule = Column(String, nullable=False)


class PatientModel(Base):
    """
    Represents a patient receiving medications.
    Beginner Note: We track chronic diseases as an array to help the ML models
    predict future medication demand based on patient demographics.
    """
    __tablename__ = "patients"

    patient_id = Column(String, primary_key=True, index=True)
    age = Column(Integer, nullable=False)
    gender = Column(String, nullable=False)
    
    # List of chronic conditions (e.g., ['Diabetes', 'Hypertension'])
    chronic_diseases = Column(ARRAY(String), default=[])


class MedicationBatchModel(Base):
    """
    Represents a specific physical batch of medications.
    Beginner Note: Instead of a flat 'inventory_count', we track exact batches.
    This allows us to know exactly when specific items expire and how much they cost.
    """
    __tablename__ = "medication_batches"

    batch_id = Column(String, primary_key=True, index=True)
    
    # Foreign key linking this batch to a specific medication
    sku_id = Column(String, ForeignKey("medications.sku_id"), nullable=False)
    
    expiry_date = Column(Date, nullable=False)
    
    # Numeric(10, 2) ensures we safely store financial values with 2 decimal places
    cost_price = Column(Numeric(10, 2), nullable=False)
    max_retail_price = Column(Numeric(10, 2), nullable=False)
    
    # The actual amount of pills/units left in this specific batch
    available_quantity = Column(Integer, nullable=False, default=0)
    
    # Physical location in the pharmacy to instruct the clerk where to go
    shelf_location = Column(String, nullable=True, default="UNASSIGNED")

    # --- Structural Indexes ---
    # Beginner Note: This composite index makes FEFO (First-Expire-First-Out) sorting extremely fast.
    # When the database looks for the oldest batch of a specific SKU, it uses this index.
    __table_args__ = (
        Index('idx_fefo_sort', 'sku_id', 'expiry_date'),
    )
