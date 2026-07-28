-- Enable pgvector extension for AI-powered semantic search on clinical knowledge
CREATE EXTENSION IF NOT EXISTS vector;

-- Table 1: Relational Metadata (Standard PostgreSQL)
-- Handles cross-industry polymorphism via JSONB
CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id VARCHAR(255) PRIMARY KEY,
    system_origin VARCHAR(100) NOT NULL,
    industry_vertical VARCHAR(100) NOT NULL,
    industry_specific_metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Table 2: Time-Series Telemetry
-- High-frequency writes, optimized for ML covariate extraction
-- tracking_id links predictions to actuals for PSI calculation
CREATE TABLE IF NOT EXISTS inventory_telemetry (
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
    supplier_id VARCHAR(255) NOT NULL REFERENCES suppliers(supplier_id),
    tracking_id VARCHAR(255),
    sku_id VARCHAR(255),
    delivery_delay_days INTEGER NOT NULL CHECK (delivery_delay_days >= 0),
    predicted_stockout_probability DOUBLE PRECISION,
    is_critical_risk BOOLEAN
);

-- Create compound index for faster querying by supplier, sku, and time
CREATE INDEX IF NOT EXISTS idx_telemetry_sku_time ON inventory_telemetry (supplier_id, sku_id, recorded_at DESC);

-- Create index on tracking_id for efficient PSI join queries
CREATE INDEX IF NOT EXISTS ix_inventory_telemetry_tracking_id ON inventory_telemetry (tracking_id);

-- Table 3: ML Prediction Log
-- Stores raw ML predictions before joining with actuals
-- Enables Population Stability Index (PSI) drift calculation
CREATE TABLE IF NOT EXISTS ml_prediction_log (
    id SERIAL PRIMARY KEY,
    tracking_id VARCHAR(255) NOT NULL,
    predicted_stockout_probability DOUBLE PRECISION NOT NULL,
    predicted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create index on tracking_id for efficient PSI queries
CREATE INDEX IF NOT EXISTS ix_ml_prediction_log_tracking_id ON ml_prediction_log (tracking_id);

-- Create index on predicted_at for time-window queries
CREATE INDEX IF NOT EXISTS ix_ml_prediction_log_predicted_at ON ml_prediction_log (predicted_at DESC);

-- Table 4: Warehouse Topology Nodes
-- Each node represents a physical location in the warehouse (storage rack, picking station, etc.)
CREATE TABLE IF NOT EXISTS warehouse_nodes (
    id VARCHAR(255) PRIMARY KEY,
    zone VARCHAR(100) NOT NULL,
    type VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Table 5: Warehouse Topology Edges (Directed Graph)
-- Each edge represents a traversable pathway between two nodes.
-- Composite primary key ensures every directed edge is unique.
CREATE TABLE IF NOT EXISTS warehouse_edges (
    source_id VARCHAR(255) NOT NULL REFERENCES warehouse_nodes(id),
    target_id VARCHAR(255) NOT NULL REFERENCES warehouse_nodes(id),
    distance_meters DOUBLE PRECISION NOT NULL,
    max_capacity INTEGER NOT NULL,
    PRIMARY KEY (source_id, target_id)
);

-- Table 6: Movement Telemetry
-- High-frequency position data from forklifts, robots, and workers.
CREATE TABLE IF NOT EXISTS movement_telemetry (
    id SERIAL,
    entity_id VARCHAR(255) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    node_id VARCHAR(255) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL
);

-- Table 9: LoRA Adapter Registry
-- Tracks fine-tuning lifecycle for prediction module adapters.
-- Status flows: TRAINING -> VALIDATING -> ACTIVE (or FAILED).
CREATE TABLE IF NOT EXISTS lora_adapter_registry (
    id VARCHAR(255) PRIMARY KEY,
    module_name VARCHAR(100) NOT NULL,
    supplier_id VARCHAR(255),
    base_model_version VARCHAR(100) NOT NULL,
    adapter_weights_path VARCHAR(500),
    checksum VARCHAR(255),
    status VARCHAR(50) NOT NULL DEFAULT 'TRAINING',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_lora_adapter_registry_module_name ON lora_adapter_registry (module_name);

-- --- Phase 13.1: Pharmacological Ledger ---

-- 1. Medications Table (The Anchor)
CREATE TABLE IF NOT EXISTS medications (
    sku_id VARCHAR(255) PRIMARY KEY,
    apis TEXT[] NOT NULL,
    therapeutic_classes TEXT[] NOT NULL,
    cdsco_schedule VARCHAR(50) NOT NULL
);

-- 2. Patients Table
CREATE TABLE IF NOT EXISTS patients (
    patient_id VARCHAR(255) PRIMARY KEY,
    age INTEGER NOT NULL,
    gender VARCHAR(50) NOT NULL,
    chronic_diseases TEXT[] DEFAULT '{}'
);

-- 3. Medication Batches Table (The Matrix)
CREATE TABLE IF NOT EXISTS medication_batches (
    batch_id VARCHAR(255) PRIMARY KEY,
    sku_id VARCHAR(255) NOT NULL REFERENCES medications(sku_id),
    expiry_date DATE NOT NULL,
    cost_price NUMERIC(10, 2) NOT NULL,
    max_retail_price NUMERIC(10, 2) NOT NULL,
    available_quantity INTEGER NOT NULL DEFAULT 0,
    shelf_location VARCHAR(255) DEFAULT 'UNASSIGNED'
);

-- 4. FEFO Structural Index
-- This index allows the database to instantly find the batch that expires next for any given SKU.
CREATE INDEX IF NOT EXISTS idx_fefo_sort ON medication_batches(sku_id, expiry_date);

-- --- Phase 14.3: Purchase Orders ---
CREATE TABLE IF NOT EXISTS purchase_orders (
    po_id VARCHAR(255) PRIMARY KEY,
    supplier_id VARCHAR(255) NOT NULL REFERENCES suppliers(supplier_id),
    sku_id VARCHAR(255) NOT NULL REFERENCES medications(sku_id),
    ordered_qty INTEGER NOT NULL,
    delivered_qty INTEGER NOT NULL DEFAULT 0,
    cost_price NUMERIC(10, 2) NOT NULL,
    expected_mrp NUMERIC(10, 2) NOT NULL,
    order_date DATE NOT NULL,
    expected_delivery_date DATE NOT NULL,
    actual_delivery_date DATE,
    status VARCHAR(50) DEFAULT 'PENDING'
);
