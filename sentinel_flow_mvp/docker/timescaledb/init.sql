-- Idempotent creation of the vector extension. 
-- This allows PostgreSQL to understand high-dimensional arrays for AI search.
CREATE EXTENSION IF NOT EXISTS vector;
