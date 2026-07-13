"""
UNIVERSAL ETL PIPELINE — CPU-Bound Clinical Knowledge Ingestion
===============================================================

Beginner Note:
    This script replaces the old ``scripts/bulk_ingest.py``. It does the
    same job — reading the Indian Essential Medicines CSV, generating
    AI vector embeddings, and storing them in the database — but with
    THREE critical improvements:

    1. HARDWARE LOCKDOWN — We hardcode ``device='cpu'`` so the Sentence-
       Transformer model NEVER tries to load CUDA. This avoids the
       Windows DLL crash (torchaudio error 0xc0000139) that plagued
       the old script.

    2. UNIVERSAL ADAPTER — The ``transform_row()`` function gracefully
       handles CSV rows with ANY set of columns. Missing clinical fields
       get safe defaults instead of crashing with a KeyError.

    3. PHASE 4 INTEGRATION — After a successful ingestion, we call
       ``increment_global_db_version_sync()`` which flushes the RAG
       response cache so the frontend immediately sees the new data.

    Pipeline stages:
        Extract   — Read CSV rows from ``data/indian_essential_meds.csv``.
        Transform — Map raw CSV fields to our ORM schema with defaults.
        Chunk     — Format each row as a readable clinical paragraph.
        Embed     — Generate a 768-dimensional vector via PubMedBERT (CPU).
        Load      — Idempotent insert into ``medications`` and
                    ``clinical_knowledge_base``, batch-committing every
                    50 records.

Usage:
    python scripts/etl_pipeline.py

Requirements:
    - PostgreSQL with pgvector extension.
    - sentence-transformers and torch (CPU-only inference).
    - The CSV must be at ``data/indian_essential_meds.csv``.
"""

import csv
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# SQLAlchemy imports — used only for database operations, NOT for ML.
# ---------------------------------------------------------------------------
from sqlalchemy.orm import Session
from tqdm import tqdm

from app.infrastructure.database import SessionLocal
from app.infrastructure.models import (
    ClinicalKnowledgeBase,
    MedicationModel,
)

# ---------------------------------------------------------------------------
# Phase 4 Cache Invalidation — imported at the end after all inserts succeed.
# ---------------------------------------------------------------------------
# Beginner Note: We import this at the TOP of the file for discoverability,
# but it is only CALLED at the very end of ``main()`` after the database
# transaction commits. This ensures the cache is never invalidated unless
# the data was actually written.
from app.core.cache import increment_global_db_version_sync

# ---------------------------------------------------------------------------
# LOGGING CONFIGURATION
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CONFIGURATION CONSTANTS
# ---------------------------------------------------------------------------

# Path to the CSV file inside the ``data/`` directory.
# We compute it relative to this script's location so it works regardless
# of which directory the user runs the script from.
CSV_FILE_PATH: str = str(
    Path(__file__).resolve().parent.parent / "data" / "indian_essential_meds.csv"
)

# How many records to insert before committing to the database.
# Larger batches = fewer database round-trips = faster ingestion.
# 50 is conservative — PostgreSQL handles it easily without memory pressure.
BATCH_COMMIT_SIZE: int = 50

# The fixed dimensionality of PubMedBERT embeddings.
# This MUST match the ``Vector(768)`` column in ``clinical_knowledge_base``.
EMBEDDING_DIMENSIONS: int = 768

# ---------------------------------------------------------------------------
# DEFAULT VALUES for missing CSV fields
# ---------------------------------------------------------------------------
# Beginner Note: The CSV may not have all the columns our ORM expects.
# Instead of crashing with a KeyError, we supply sensible defaults.
# These are safe "seed" values — a human curator can refine them later.

DEFAULT_PREGNANCY_CATEGORY: str = "C"
"""
FDA Category C means "Animal studies show risk, but human studies are lacking."
We default to C because it is the safest middle-ground assumption for an
unclassified drug — it forces the pharmacist to consult a doctor before
dispensing to a pregnant patient, which is exactly what you want for
unvetted seed data.
"""

DEFAULT_PEDIATRIC_AGE_THRESHOLD_MONTHS: int = 0
"""
Zero means "no age restriction." We default to 0 because most adult
medications in the Indian Essential Medicines list are not specifically
contraindicated for children — they simply lack pediatric clinical trial
data. Setting a positive threshold would be misleading.
"""

DEFAULT_IS_APPROVED_BY_CURATOR: bool = True
"""
We set this to True because this CSV IS our master seed dataset — it was
curated by the CDSCO (Indian government). Future regulatory changes will
enter with is_approved_by_curator = False and require human review.
"""

DEFAULT_CDSCO_SCHEDULE: str = "OTC"
"""
Over-the-counter by default. Many essential medicines (paracetamol,
antacids, etc.) are OTC in India. Prescription-only drugs will be
recategorized during curation.
"""

DEFAULT_THERAPEUTIC_CLASS: str = "General Medicine"
"""
A catch-all therapeutic class for seed data. Pharmacists can reclassify
drugs into more specific categories (e.g., "Cardiology", "Endocrinology")
during curation.
"""


# =====================================================================
# STEP 1 — EXTRACT: Read CSV Rows
# =====================================================================
# Beginner Note: This is the "E" in ETL. We open the CSV file and read
# every row into a list of Python dictionaries. Each dictionary has keys
# matching the CSV column headers (sku_id, brand_name, generic_name, etc.).
# =====================================================================


def extract_csv_rows(csv_path: str) -> list[dict]:
    """
    Read the Indian Essential Medicines CSV into a list of dictionaries.

    Args:
        csv_path: Absolute path to the CSV file.

    Returns:
        A list of dicts, one per row. Returns an empty list if the file
        does not exist or is empty.

    Raises:
        FileNotFoundError: If the CSV file does not exist.
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f"CSV file not found at: {csv_path}. "
            "Did you run the Phase 5 setup that moved it into data/?"
        )

    rows: list[dict] = []
    logger.info("Extract: Reading CSV from %s", csv_path)

    with open(csv_path, mode="r", encoding="utf-8") as file_handle:
        csv_reader = csv.DictReader(file_handle)

        for row_index, row in enumerate(csv_reader, start=1):
            # Strip whitespace from every value to keep data clean.
            cleaned_row: dict = {
                key.strip(): value.strip() if value else ""
                for key, value in row.items()
            }
            rows.append(cleaned_row)

    logger.info("Extract: Loaded %d rows from CSV.", len(rows))
    return rows


# =====================================================================
# STEP 2 — TRANSFORM: Map CSV Fields to ORM Schema
# =====================================================================
# Beginner Note: This is the "T" in ETL. The CSV has a flat structure
# (brand_name, generic_name, price_inr) but our database has a richer
# schema (apis ARRAY, pregnancy_category, etc.). We bridge the gap here
# by renaming, reshaping, and filling in defaults.
# =====================================================================


def transform_row(row: dict) -> dict:
    """
    Accept a raw CSV row dictionary and return a cleaned dict safe for
    database insertion.

    This function NEVER crashes on missing keys. Every field access uses
    ``.get()`` with a safe default.

    Args:
        row: A single CSV row dictionary. May have any subset of columns.

    Returns:
        A dictionary with keys matching our ORM schema:
            sku_id, name, apis, therapeutic_classes, cdsco_schedule,
            pregnancy_category, pediatric_age_threshold_months,
            is_approved_by_curator, brand_name, generic_name,
            indications, side_effects, contraindications, price_inr.
    """
    # ------------------------------------------------------------------
    # Core identifiers — these MUST exist for the row to be useful.
    # We use .get() so missing keys return empty string instead of error.
    # ------------------------------------------------------------------
    sku_id: str = row.get("sku_id", "").strip()
    brand_name: str = row.get("brand_name", "").strip()
    generic_name: str = row.get("generic_name", "").strip()

    # ------------------------------------------------------------------
    # Clinical text fields — used to build the semantic chunk.
    # We default to empty string so the chunk is still readable.
    # ------------------------------------------------------------------
    indications: str = row.get("indications", "").strip()
    side_effects: str = row.get("side_effects", "").strip()
    contraindications: str = row.get("contraindications", "").strip()
    price_inr: str = row.get("price_inr", "").strip()

    # ------------------------------------------------------------------
    # Safety defaults for missing clinical master index fields
    # ------------------------------------------------------------------
    # These are the Phase 1 fields. The old script did not set them at
    # all — they were left as NULL. We now supply sensible defaults.
    pregnancy_category: str = (
        row.get("pregnancy_category", "").strip()
        or DEFAULT_PREGNANCY_CATEGORY
    )

    # Parse pediatric_age_threshold_months as integer, defaulting to 0.
    raw_age: str = row.get("pediatric_age_threshold_months", "").strip()
    if raw_age:
        try:
            pediatric_age_threshold_months: int = int(raw_age)
        except (ValueError, TypeError):
            pediatric_age_threshold_months: int = DEFAULT_PEDIATRIC_AGE_THRESHOLD_MONTHS
    else:
        pediatric_age_threshold_months: int = DEFAULT_PEDIATRIC_AGE_THRESHOLD_MONTHS

    # ------------------------------------------------------------------
    # Build the transformed output dictionary
    # ------------------------------------------------------------------
    # We structure this to mirror the MedicationModel + ClinicalKnowledgeBase
    # fields so the Load stage has a single source of truth.
    transformed: dict = {
        # --- MedicationModel fields ---
        "sku_id": sku_id,
        "apis": [generic_name] if generic_name else ["Unknown"],
        "therapeutic_classes": [DEFAULT_THERAPEUTIC_CLASS],
        "cdsco_schedule": DEFAULT_CDSCO_SCHEDULE,
        "pregnancy_category": pregnancy_category,
        "pediatric_age_threshold_months": pediatric_age_threshold_months,
        "is_approved_by_curator": DEFAULT_IS_APPROVED_BY_CURATOR,
        # --- ClinicalKnowledgeBase metadata ---
        "brand_name": brand_name,
        "generic_name": generic_name,
        "indications": indications,
        "side_effects": side_effects,
        "contraindications": contraindications,
        "price_inr": price_inr,
    }

    return transformed


# =====================================================================
# STEP 3 — SEMANTIC CHUNK: Format Row as Clinical Paragraph
# =====================================================================
# Beginner Note: The AI model (PubMedBERT) doesn't understand CSV columns.
# It understands plain English sentences. We combine all the clinical data
# into a single, readable paragraph that captures the FULL clinical picture
# of this medication. The vector search engine will compare user queries
# against this paragraph.
# =====================================================================


def create_semantic_chunk(transformed_data: dict) -> str:
    """
    Format a transformed row into a readable clinical paragraph.

    The paragraph is designed for the PubMedBERT vector search engine:
    it includes the drug name, indications, side effects, and
    contraindications in a structured but natural-language format.

    Args:
        transformed_data: The dictionary returned by ``transform_row()``.

    Returns:
        A plain-text string suitable for embedding and search.
    """
    # Extract fields with .get() for safety.
    sku: str = transformed_data.get("sku_id", "UNKNOWN")
    brand: str = transformed_data.get("brand_name", "")
    generic: str = transformed_data.get("generic_name", "")
    indications: str = transformed_data.get("indications", "")
    side_effects: str = transformed_data.get("side_effects", "")
    contraindications: str = transformed_data.get("contraindications", "")
    price: str = transformed_data.get("price_inr", "")

    # Build the chunk piece by piece so it is easy to read and modify.
    # Each section starts with a label so keyword search can find it.
    lines: list[str] = []

    lines.append(f"SKU: {sku}.")
    if brand:
        lines.append(f"Brand: {brand}.")
    if generic:
        lines.append(f"Generic: {generic}.")
    if indications:
        # Replace semicolons with commas for readability.
        cleaned_indications: str = indications.replace(";", ",")
        lines.append(f"Indications: {cleaned_indications}.")
    if side_effects:
        cleaned_side_effects: str = side_effects.replace(";", ",")
        lines.append(f"Side Effects: {cleaned_side_effects}.")
    if contraindications:
        cleaned_contraindications: str = contraindications.replace(";", ",")
        lines.append(f"Contraindications: {cleaned_contraindications}.")
    if price:
        lines.append(f"Price (INR): {price}.")

    # Join all lines with a single space to form one coherent paragraph.
    chunk: str = " ".join(lines)

    return chunk


# =====================================================================
# STEP 4 — EMBED: Generate Vector (CPU Only, Hardcoded)
# =====================================================================
# Beginner Note: This is the heart of the hardware lockdown. We load
# PubMedBERT with ``device='cpu'`` — this is NOT configurable. Even if
# the machine has a 24GB NVIDIA GPU, we force CPU inference.
#
# Why? Because on Windows, torchaudio's CUDA binaries crash with
# "OSError: [WinError 127] The specified procedure could not be found"
# whenever any torch-dependent library (transformers, sentence_transformers)
# is imported. Running on CPU side-steps this entirely.
#
# The performance trade-off is acceptable for seed data ingestion:
#   - Our CSV is ~200 rows (tiny by ML standards).
#   - CPU encoding of 200 rows takes ~30-60 seconds.
#   - This is a one-time operation, not a real-time API call.
# =====================================================================


def _load_embedding_model():
    """
    Load the PubMedBERT embedding model on CPU.

    This function is called ONCE and the model is cached globally for
    the lifetime of the script. The ``device='cpu'`` is hardcoded and
    MUST NOT be changed to 'cuda' or 'auto'.

    Returns:
        A SentenceTransformer instance ready for ``.encode()``.
    """
    # Lazy import: We import SentenceTransformer INSIDE this function
    # so that the script can at least be IMPORTED without crashing.
    # The torch/sentence_transformers dependencies are only loaded when
    # this function is actually called (i.e., when the user runs the script).
    from sentence_transformers import SentenceTransformer

    logger.info("Embed: Loading PubMedBERT model onto CPU (hardcoded)...")
    model = SentenceTransformer(
        "NeuML/pubmedbert-base-embeddings",
        device="cpu",  # HARDCODED — never change this.
    )
    logger.info("Embed: PubMedBERT model loaded successfully on CPU.")
    return model


def generate_embeddings(
    model,
    chunks: list[str],
    batch_size: int = 32,
) -> list[list[float]]:
    """
    Convert a list of text chunks into 768-dimensional vectors.

    Args:
        model: The SentenceTransformer model (loaded on CPU).
        chunks: List of plain-text clinical paragraphs.
        batch_size: How many chunks to encode per batch (default 32).

    Returns:
        A list of float vectors, each of length 768.
    """
    all_embeddings: list[list[float]] = []
    total: int = len(chunks)

    logger.info("Embed: Generating %d embeddings (batch_size=%d)...", total, batch_size)

    for batch_start in tqdm(
        range(0, total, batch_size),
        desc="Embedding batches",
        unit="batch",
    ):
        batch_end: int = min(batch_start + batch_size, total)
        batch_texts: list[str] = chunks[batch_start:batch_end]

        # Encode returns a numpy array. .tolist() converts it to a
        # plain Python list of floats that pgvector can store.
        batch_vectors: list[list[float]] = model.encode(
            batch_texts,
            batch_size=batch_size,
            show_progress_bar=False,
        ).tolist()

        all_embeddings.extend(batch_vectors)

    logger.info("Embed: Generated %d embeddings (dim=%d).", len(all_embeddings), EMBEDDING_DIMENSIONS)
    return all_embeddings


# =====================================================================
# STEP 5 — LOAD: Idempotent Database Insert
# =====================================================================
# Beginner Note: This is the "L" in ETL. We insert each transformed row
# into the database, but only if it does NOT already exist. This makes
# the script IDEMPOTENT — running it twice produces the exact same result
# as running it once.
#
# We commit every BATCH_COMMIT_SIZE (50) records to avoid holding a
# giant uncommitted transaction that could bloat the database.
# =====================================================================


def load_medication_record(
    db_session: Session,
    transformed: dict,
) -> bool:
    """
    Insert or skip a medication record in the ``medications`` table.

    Args:
        db_session: Active SQLAlchemy session.
        transformed: The output of ``transform_row()``.

    Returns:
        True if a new record was created, False if it already existed.
    """
    sku_id: str = transformed["sku_id"]

    # Check if this SKU already exists in the database.
    existing: Optional[MedicationModel] = (
        db_session.query(MedicationModel)
        .filter(MedicationModel.sku_id == sku_id)
        .first()
    )

    if existing:
        return False  # Already exists — skip.

    # Create a new MedicationModel record with our transformed data.
    new_record: MedicationModel = MedicationModel(
        sku_id=sku_id,
        apis=transformed["apis"],
        therapeutic_classes=transformed["therapeutic_classes"],
        cdsco_schedule=transformed["cdsco_schedule"],
        pregnancy_category=transformed["pregnancy_category"],
        pediatric_age_threshold_months=transformed["pediatric_age_threshold_months"],
        is_approved_by_curator=transformed["is_approved_by_curator"],
    )
    db_session.add(new_record)
    return True


def load_knowledge_record(
    db_session: Session,
    sku_id: str,
    chunk: str,
    embedding: list[float],
    metadata_payload: dict,
) -> bool:
    """
    Insert or skip a clinical knowledge record with its vector embedding.

    Args:
        db_session: Active SQLAlchemy session.
        sku_id: The medication's SKU identifier.
        chunk: The semantic chunk (clinical paragraph).
        embedding: The 768-dimensional vector.
        metadata_payload: Dict with brand_name, generic_name, price, etc.

    Returns:
        True if a new record was created, False if it already existed.
    """
    # Check for duplicate — same SKU + same content text.
    existing: Optional[ClinicalKnowledgeBase] = (
        db_session.query(ClinicalKnowledgeBase)
        .filter(
            ClinicalKnowledgeBase.sku_id == sku_id,
            ClinicalKnowledgeBase.content == chunk,
        )
        .first()
    )

    if existing:
        return False

    new_record: ClinicalKnowledgeBase = ClinicalKnowledgeBase(
        sku_id=sku_id,
        content=chunk,
        embedding=embedding,
        metadata_payload=metadata_payload,
    )
    db_session.add(new_record)
    return True


# =====================================================================
# MAIN — Orchestrate the Full ETL Pipeline
# =====================================================================


def main() -> None:
    """
    Execute the complete ETL pipeline:
        Extract → Transform → Chunk → Embed → Load → Cache Invalidate
    """
    start_time: float = time.time()

    print("=" * 72)
    print("  UNIVERSAL ETL PIPELINE — CPU-Bound Clinical Knowledge Ingestion")
    print("=" * 72)

    # ==================================================================
    # STAGE 1: Extract
    # ==================================================================
    print("\n--- STAGE 1: Extract ---")
    try:
        raw_rows: list[dict] = extract_csv_rows(CSV_FILE_PATH)
    except FileNotFoundError as error:
        logger.error(str(error))
        sys.exit(1)

    if not raw_rows:
        logger.error("Extract: No rows found in CSV. Aborting.")
        sys.exit(1)

    # ==================================================================
    # STAGE 2: Transform
    # ==================================================================
    print("\n--- STAGE 2: Transform ---")
    logger.info("Transform: Processing %d rows...", len(raw_rows))

    transformed_rows: list[dict] = []
    for row in raw_rows:
        try:
            transformed: dict = transform_row(row)
            transformed_rows.append(transformed)
        except Exception as error:
            # Log the problematic row and continue with the next one.
            # A single bad row should not crash the entire ingestion.
            sku: str = row.get("sku_id", "UNKNOWN")
            logger.warning(
                "Transform: Skipping row SKU=%s due to error: %s",
                sku, error,
            )

    logger.info(
        "Transform: Successfully transformed %d / %d rows.",
        len(transformed_rows),
        len(raw_rows),
    )

    # ==================================================================
    # STAGE 3: Chunk
    # ==================================================================
    print("\n--- STAGE 3: Semantic Chunking ---")
    chunks: list[str] = []
    for t_row in transformed_rows:
        chunk: str = create_semantic_chunk(t_row)
        chunks.append(chunk)

    logger.info("Chunk: Created %d semantic chunks.", len(chunks))

    # Display the first chunk as a sample so the operator can verify.
    if chunks:
        print(f"  Sample chunk:\n    {chunks[0][:200]}...")

    # ==================================================================
    # STAGE 4: Embed (CPU Only)
    # ==================================================================
    print("\n--- STAGE 4: Embed (CPU Locked) ---")
    model = _load_embedding_model()
    embeddings: list[list[float]] = generate_embeddings(model, chunks)

    # ==================================================================
    # STAGE 5: Load (Idempotent, Batch-Committed)
    # ==================================================================
    print("\n--- STAGE 5: Load ---")
    db_session: Session = SessionLocal()

    medications_created: int = 0
    knowledge_created: int = 0
    batch_counter: int = 0

    try:
        for index, t_row in enumerate(transformed_rows):
            sku_id: str = t_row["sku_id"]
            chunk: str = chunks[index]
            embedding: list[float] = embeddings[index]

            # --- Step 5a: Insert Medication (parent record) ---
            if load_medication_record(db_session, t_row):
                medications_created += 1

            # --- Step 5b: Insert Clinical Knowledge (child record) ---
            metadata: dict = {
                "brand_name": t_row.get("brand_name", ""),
                "generic_name": t_row.get("generic_name", ""),
                "price_inr": t_row.get("price_inr", ""),
                "indications": t_row.get("indications", ""),
                "side_effects": t_row.get("side_effects", ""),
                "contraindications": t_row.get("contraindications", ""),
            }
            if load_knowledge_record(db_session, sku_id, chunk, embedding, metadata):
                knowledge_created += 1

            # --- Step 5c: Batch Commit ---
            batch_counter += 1
            if batch_counter >= BATCH_COMMIT_SIZE:
                db_session.commit()
                logger.info(
                    "Load: Batch committed (%d records). "
                    "Medications created so far: %d. Knowledge created so far: %d.",
                    BATCH_COMMIT_SIZE,
                    medications_created,
                    knowledge_created,
                )
                batch_counter = 0

        # Final commit for any remaining records.
        if batch_counter > 0:
            db_session.commit()
            logger.info(
                "Load: Final batch committed (%d records).",
                batch_counter,
            )

        db_session.close()

        elapsed: float = time.time() - start_time
        print("\n" + "=" * 72)
        print("  INGESTION COMPLETE")
        print("=" * 72)
        print(f"  CSV rows loaded:              {len(raw_rows)}")
        print(f"  Rows transformed:             {len(transformed_rows)}")
        print(f"  Medications created:          {medications_created}")
        print(f"  Knowledge records created:    {knowledge_created}")
        print(f"  Vector dimensions:            {EMBEDDING_DIMENSIONS}")
        print(f"  Hardware:                     CPU (hardcoded)")
        print(f"  Elapsed time:                 {elapsed:.1f}s")

        # ==============================================================
        # PHASE 4 INTEGRATION: Flush the RAG Cache
        # ==============================================================
        # Beginner Note: After successfully inserting new data, we
        # increment the global DB version counter in Redis. This
        # instantly invalidates ALL cached RAG responses because their
        # cache keys include the old version number. The next time a
        # pharmacist asks a clinical question, the RAG pipeline will
        # re-query the database and generate a fresh response that
        # includes the new data.
        print("\n--- Phase 4 Sync: Invalidating RAG Cache ---")
        try:
            new_version: str = increment_global_db_version_sync()
            logger.info(
                "Cache invalidation complete. Global DB version is now %s.",
                new_version,
            )
        except Exception as cache_error:
            # Redis might not be running. This is non-fatal — the
            # ingestion succeeded, but the cache will serve stale data
            # until the next pipeline run with Redis available.
            logger.warning(
                "Cache invalidation skipped (Redis may be offline): %s",
                cache_error,
            )
        print("=" * 72)

    except Exception as error:
        db_session.rollback()
        logger.error("Load: Transaction rolled back due to error: %s", error)
        raise
    finally:
        if db_session.is_active:
            db_session.close()


if __name__ == "__main__":
    main()
