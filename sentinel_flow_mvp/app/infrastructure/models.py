"""SQLAlchemy ORM Models for Database Persistence.

Defines the mapping between Python objects and the underlying PostgreSQL/TimescaleDB tables.
"""

from datetime import datetime, timezone
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Date, Index, Numeric, text, Text, JSON, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Tenant(Base):
    """
    Domain Model: SaaS Tenant (Pharmacy/Organization).
    Stores isolated credentials for multi-tenant WhatsApp and UPI integrations.
    """
    __tablename__ = "tenants"

    tenant_id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    
    # Per-Tenant Integrations
    upi_id = Column(String, nullable=True)
    meta_whatsapp_token = Column(String, nullable=True)
    whatsapp_phone_id = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean, default=True)

    # Pincode is required to fetch localized weather and search trends
    pincode = Column(String, index=True, nullable=True)


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

# --- Phase 14.3: Procurement & Distributor Tracking ---

class PurchaseOrderModel(Base):
    """
    Tracks orders placed with distributors to measure their reliability.
    Beginner Note: By comparing 'ordered_qty' with 'delivered_qty', we can 
    calculate exactly how much stock the distributor failed to deliver.
    """
    __tablename__ = "purchase_orders"

    po_id = Column(String, primary_key=True, index=True)
    
    # Links to the supplier/distributor who is supposed to deliver this
    supplier_id = Column(String, ForeignKey("suppliers.supplier_id"), nullable=False)
    
    # Links to the specific medication ordered
    sku_id = Column(String, ForeignKey("medications.sku_id"), nullable=False)
    
    # Quantities
    ordered_qty = Column(Integer, nullable=False)
    delivered_qty = Column(Integer, nullable=False, default=0)
    
    # Financials (Stored at the time of order to lock in the expected margins)
    cost_price = Column(Numeric(10, 2), nullable=False)
    expected_mrp = Column(Numeric(10, 2), nullable=False)
    
    # Timelines
    order_date = Column(Date, nullable=False)
    expected_delivery_date = Column(Date, nullable=False)
    actual_delivery_date = Column(Date, nullable=True)
    
    status = Column(String, default="PENDING") # PENDING, DELIVERED, PARTIAL, FAILED

# ==========================================
# PHASE 15.1: CLINICAL KNOWLEDGE BASE (VECTOR DB)
# ==========================================

class ClinicalKnowledgeBase(Base):
    """
    Domain Model: Clinical Knowledge Base.
    Stores medical guidelines and their vector embeddings for semantic search.
    """
    __tablename__ = "clinical_knowledge_base"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign Key linking to the specific medication (SKU)
    sku_id = Column(String, ForeignKey("medications.sku_id"), nullable=False, index=True)
    
    # The actual human-readable text (e.g., "Contraindicated in 3rd trimester of pregnancy")
    content = Column(Text, nullable=False)
    
    # The AI representation of the text. 
    # We use 768 dimensions because PubMedBERT outputs exactly 768 numbers.
    embedding = Column(Vector(768), nullable=False)
    
    # Flexible metadata (e.g., source URL, CDSCO schedule, confidence score)
    metadata_payload = Column(JSON, default={})


# ==========================================
# PHASE 16: PATIENT CRM & ADHERENCE LEDGER
# ==========================================

class Patient(Base):
    """Domain Model: Patient Profile."""
    __tablename__ = "patients"

    patient_id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.tenant_id"), nullable=False, index=True, default="system_admin")
    name = Column(String, nullable=False)
    phone_number = Column(String, unique=True, index=True, nullable=False)
    age = Column(Integer)
    gender = Column(String)
    chronic_diseases = Column(JSON, default=[])
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class TreatmentPlan(Base):
    """Domain Model: Medication Adherence Ledger."""
    __tablename__ = "treatment_plans"

    plan_id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.tenant_id"), nullable=False, index=True, default="system_admin")
    patient_id = Column(String, ForeignKey("patients.patient_id"), nullable=False, index=True)
    sku_id = Column(String, nullable=False, index=True)

    daily_dosage = Column(Float, nullable=False)
    total_quantity_dispensed = Column(Integer, nullable=False)

    start_date = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    projected_depletion_date = Column(DateTime, nullable=False, index=True)

    is_active = Column(Boolean, default=True)


# --- NEW MODEL ---
class ExogenousCovariateModel(Base):
    """
    Stores external data (weather, search trends) by pincode and time.
    Used by the ML Engine to predict demand spikes (e.g., rain -> fever meds).
    """
    __tablename__ = "exogenous_covariates"

    id = Column(Integer, primary_key=True, index=True)
    pincode = Column(String, index=True, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Weather Metrics
    humidity_percent = Column(Float, nullable=True)
    rain_mm = Column(Float, nullable=True)
    
    # Search Trend Metrics
    symptom_keyword = Column(String, nullable=True) # e.g., "dengue symptoms"
    trend_score = Column(Float, nullable=True) # 0 to 100 scale

    # Idempotency: Prevent duplicate entries for the same location, time, and keyword
    __table_args__ = (
        UniqueConstraint('pincode', 'timestamp', 'symptom_keyword', name='uix_pincode_time_keyword'),
    )


class NotificationModel(Base):
    """
    Persistent ledger for all system alerts (Disease Waves, Stockouts, etc.)
    Ensures alerts are not lost upon page refresh.
    """
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String, index=True, nullable=False)
    title = Column(String, nullable=False)
    message = Column(String, nullable=False)
    alert_type = Column(String, nullable=False) # e.g., "DISEASE_WAVE", "SYSTEM"
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ==========================================
# PHASE 17: POS CHECKOUT & PRAGMATIC OUTBOX
# ==========================================

class SaleReceiptModel(Base):
    """
    Beginner Note: This model acts as the header for a single customer checkout transaction.
    It records when the sale occurred, the total amount collected, and optionally
    links back to a known patient so we can send automated refill reminders.
    """
    __tablename__ = "sale_receipts"

    id = Column(String, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    total_amount_inr = Column(Numeric(10, 2), nullable=False)
    payment_method = Column(String(10), nullable=False, server_default=text("'CASH'"))

    # Optional foreign key to link this receipt to a known patient for refill messaging
    patient_id = Column(String, ForeignKey("patients.patient_id"), nullable=True, index=True)

    lines = relationship("SaleLineItemModel", back_populates="receipt")


class SaleLineItemModel(Base):
    """
    Beginner Note: This model records every specific item purchased during the checkout.
    It links back to the SaleReceiptModel and deducts from MedicationBatchModel.
    """
    __tablename__ = "sale_line_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    receipt_id = Column(String, ForeignKey("sale_receipts.id"), nullable=False, index=True)
    batch_id = Column(String, ForeignKey("medication_batches.batch_id"), nullable=False)
    name = Column(String(255), nullable=False, server_default=text("''"))

    quantity_sold = Column(Integer, nullable=False)
    price_per_unit = Column(Numeric(10, 2), nullable=False)

    receipt = relationship("SaleReceiptModel", back_populates="lines")


class OutboxEventModel(Base):
    """
    Beginner Note: This is the core of the Pragmatic Transactional Outbox pattern.
    Instead of directly calling external services (which might fail and cause data inconsistency),
    we save an 'event' in the exact same database transaction as the sale.
    A background worker will later read this table and send data to Kafka/Analytics reliably.
    """
    __tablename__ = "outbox_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String, nullable=False, index=True) # e.g., 'checkout_completed'
    payload = Column(JSONB, nullable=False) # Stores the exact details of the sale in JSON format
    status = Column(String, default="pending", index=True) # 'pending', 'processing', 'completed', 'failed'
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
