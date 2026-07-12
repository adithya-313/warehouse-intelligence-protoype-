"""
GPU-Accelerated Bulk Clinical Knowledge Ingestion Engine.

Beginner Note:
    This script is the heavy machinery that converts the Indian Essential
    Medicines CSV file into AI-searchable vector embeddings. It is designed
    to run on a machine with an NVIDIA GPU (CUDA) for maximum throughput,
    but gracefully falls back to CPU if no GPU is available.

    The pipeline has four stages:
      1. CSV Reading — Load every row from the CSV file into memory.
      2. Parent Record Creation — Ensure each SKU has a row in the
         ``medications`` table FIRST (because ``clinical_knowledge_base``
         has a foreign key constraint referencing ``medications.sku_id``).
      3. Embedding Generation — Use PubMedBERT to convert the clinical
         text into a 768-dimensional vector. We process in BATCHES of 128
         to prevent GPU memory overflow.
      4. Database Insert — Bulk-insert the vectors into
         ``clinical_knowledge_base`` using ``ON CONFLICT DO NOTHING`` so
         we never create duplicate entries for the same SKU.

    Usage:
        python scripts/bulk_ingest.py

    Requirements:
        - PostgreSQL with pgvector extension (running on localhost:5432).
        - sentence-transformers + torch (with CUDA if available).
        - The CSV file must be at ``sentinel_flow_mvp/indian_essential_meds.csv``.
"""

import csv
import logging
import os
import sys
from datetime import datetime
from typing import Optional

# ---------------------------------------------------------------------------
# We import torch FIRST to check for GPU availability before loading the model.
# CUDA (Compute Unified Device Architecture) is NVIDIA's parallel computing
# platform. If a compatible GPU is present, torch.cuda.is_available() returns
# True and we can run the AI model 10-50x faster than on CPU.
# ---------------------------------------------------------------------------
import torch
from sqlalchemy.orm import Session
from tqdm import tqdm

# Import our database session and models from the application.
# We use the EXISTING infrastructure so this script is consistent with
# the running application's schema and connection settings.
from app.infrastructure.database import SessionLocal, engine
from app.infrastructure.models import (
    ClinicalKnowledgeBase,
    MedicationModel,
    MedicationBatchModel,
    Base,
)

# ---------------------------------------------------------------------------
# LOGGING CONFIGURATION
# We log to both the console (so the developer sees progress) and include
# timestamps so we can measure how long each stage takes.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CONFIGURATION CONSTANTS
# These are tuned for a typical NVIDIA GPU with 8GB VRAM (e.g., RTX 3070).
# If you have a GPU with less memory (e.g., 4GB), reduce BATCH_SIZE to 64.
# If you have a data-center GPU (e.g., A100 80GB), you can increase to 512.
# ---------------------------------------------------------------------------
CSV_FILE_PATH: str = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "indian_essential_meds.csv",
)

# Batch size for SentenceTransformer encoding.
# Larger batches = faster throughput, but higher GPU memory usage.
# 128 is a safe default that works on most GPUs with 8GB+ VRAM.
BATCH_SIZE: int = 128

# The number of dimensions for the PubMedBERT model.
# This MUST match the ClinicalKnowledgeBase.embedding column definition
# which is Vector(768). Changing this would break the database schema.
EMBEDDING_DIMENSIONS: int = 768


def detect_device() -> str:
    """
    Detect whether a CUDA-capable NVIDIA GPU is available.

    Beginner Note:
        CUDA is NVIDIA's technology for running computations on the GPU.
        GPUs have thousands of small cores that can process many math
        operations simultaneously — perfect for neural network inference.
        If no GPU is detected, we fall back to CPU (slower but universal).

    Returns:
        ``"cuda"`` if a GPU is available, ``"cpu"`` otherwise.
    """
    if torch.cuda.is_available():
        gpu_name: str = torch.cuda.get_device_name(0)
        gpu_memory: float = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        logger.info(
            "CUDA GPU detected: %s (%.1f GB VRAM). Using GPU acceleration.",
            gpu_name,
            gpu_memory,
        )
        return "cuda"
    else:
        logger.warning(
            "No CUDA GPU detected. Falling back to CPU. "
            "This will be significantly slower for large datasets."
        )
        return "cpu"


def load_model(device: str):
    """
    Load the PubMedBERT embedding model from HuggingFace.

    Beginner Note:
        PubMedBERT is a BERT model that was trained on millions of medical
        research papers from PubMed. It understands medical terminology
        (e.g., it knows that "myocardial infarction" is the same as "heart
        attack" in terms of meaning). The model outputs a 768-dimensional
        vector for any input text — this is what pgvector stores and
        searches against.

    Args:
        device: ``"cuda"`` or ``"cpu"`` — where to run the model.

    Returns:
        A SentenceTransformer model instance ready for encoding.
    """
    from sentence_transformers import SentenceTransformer

    logger.info("Loading PubMedBERT model onto %s... This may take a moment.", device)
    model = SentenceTransformer(
        "NeuML/pubmedbert-base-embeddings",
        device=device,
    )
    logger.info("PubMedBERT model loaded successfully on %s.", device)
    return model


def read_csv_rows(csv_path: str) -> list[dict]:
    """
    Read the Indian Essential Medicines CSV into a list of dictionaries.

    Beginner Note:
        Each row in the CSV represents one medication (SKU). We combine the
        brand name, generic name, indications, side effects, and
        contraindications into a single text block that the AI model can
        understand. This combined text becomes the ``content`` field in
        the clinical_knowledge_base table.

    Args:
        csv_path: Absolute path to the CSV file.

    Returns:
        A list of dictionaries with keys: sku_id, brand_name, generic_name,
        indications, side_effects, contraindications, formatted_text, price_inr.
    """
    rows: list[dict] = []

    logger.info("Reading CSV file: %s", csv_path)

    with open(csv_path, mode="r", encoding="utf-8") as file_handle:
        csv_reader = csv.DictReader(file_handle)

        for row_index, row in enumerate(csv_reader, start=1):
            # Strip whitespace from all values to avoid data quality issues.
            cleaned_row: dict = {
                key.strip(): value.strip() if value else ""
                for key, value in row.items()
            }

            # Build the formatted clinical text that will be embedded.
            # This is the text the AI search engine will compare against
            # when a pharmacist asks a clinical question.
            formatted_text: str = (
                f"Brand: {cleaned_row.get('brand_name', '')}. "
                f"Generic: {cleaned_row.get('generic_name', '')}. "
                f"Indications: {cleaned_row.get('indications', '')}. "
                f"Side Effects: {cleaned_row.get('side_effects', '')}. "
                f"Contraindications: {cleaned_row.get('contraindications', '')}."
            )

            cleaned_row["formatted_text"] = formatted_text
            rows.append(cleaned_row)

    logger.info("Loaded %d rows from CSV.", len(rows))
    return rows


def ensure_parent_medications_exist(
    database_session: Session,
    csv_rows: list[dict],
) -> int:
    """
    Create parent ``medications`` rows BEFORE inserting clinical knowledge.

    Beginner Note:
        The ``clinical_knowledge_base`` table has a foreign key constraint
        named ``clinical_knowledge_base_sku_id_fkey`` that references
        ``medications(sku_id)``. This means we MUST have a row in the
        ``medications`` table for every SKU we want to insert into
        ``clinical_knowledge_base``. If we try to insert without the parent
        row, PostgreSQL throws a foreign key violation error.

    This function:
        1. Checks if each SKU already exists in ``medications``.
        2. If not, creates a minimal parent record with placeholder values.
        3. Commits the new parent records so the FK constraint is satisfied.

    Args:
        database_session: Active SQLAlchemy session.
        csv_rows: The list of rows loaded from the CSV.

    Returns:
        The number of new parent medication records created.
    """
    created_count: int = 0
    skipped_count: int = 0

    for row in csv_rows:
        sku_id: str = row["sku_id"]

        # Check if this SKU already exists in the medications table.
        existing_medication: Optional[MedicationModel] = (
            database_session.query(MedicationModel)
            .filter(MedicationModel.sku_id == sku_id)
            .first()
        )

        if existing_medication:
            skipped_count += 1
            continue

        # Create a new parent medication record.
        # We extract the generic name as the API (Active Pharmaceutical
        # Ingredient) and classify it under a general therapeutic class.
        new_medication: MedicationModel = MedicationModel(
            sku_id=sku_id,
            apis=[row.get("generic_name", "Unknown")],
            therapeutic_classes=["General Medicine"],
            cdsco_schedule="OTC",  # Over-the-counter by default
        )
        database_session.add(new_medication)
        created_count += 1

    # Commit all new parent records at once.
    database_session.commit()

    logger.info(
        "Parent medications check complete. Created %d new SKU(s). Skipped %d existing.",
        created_count,
        skipped_count,
    )
    return created_count


def batch_generate_embeddings(
    model,
    texts: list[str],
    batch_size: int,
    device: str,
) -> list[list[float]]:
    """
    Generate 768-dimensional embeddings for a list of texts in batches.

    Beginner Note:
        GPU memory is limited (typically 8–24 GB). If we try to encode ALL
        texts at once, we will run out of memory and the program will crash
        with a CUDA out-of-memory (OOM) error. To prevent this, we split
        the texts into small batches and encode one batch at a time.

        Each batch produces a 2D numpy array of shape (batch_size, 768).
        We convert each row to a Python list (which pgvector can store).

    Args:
        model: The SentenceTransformer model.
        texts: All text strings to encode.
        batch_size: How many texts to encode in one GPU batch.
        device: ``"cuda"`` or ``"cpu"``.

    Returns:
        A list of 768-dimensional float vectors (one per input text).
    """
    all_embeddings: list[list[float]] = []
    total_texts: int = len(texts)

    # tqdm shows a progress bar so the developer knows how fast we're going.
    for batch_start in tqdm(
        range(0, total_texts, batch_size),
        desc="Encoding batches",
        unit="batch",
    ):
        batch_end: int = min(batch_start + batch_size, total_texts)
        batch_texts: list[str] = texts[batch_start:batch_end]

        # Encode the batch. The model returns a numpy array.
        # .tolist() converts each numpy row to a plain Python list of floats.
        batch_embeddings: list[list[float]] = model.encode(
            batch_texts,
            batch_size=batch_size,
            show_progress_bar=False,  # We use tqdm instead
        ).tolist()

        all_embeddings.extend(batch_embeddings)

    logger.info(
        "Generated %d embeddings. Vector dimension: %d.",
        len(all_embeddings),
        EMBEDDING_DIMENSIONS,
    )
    return all_embeddings


def bulk_insert_knowledge(
    database_session: Session,
    csv_rows: list[dict],
    embeddings: list[list[float]],
) -> int:
    """
    Bulk-insert clinical knowledge records with their vector embeddings.

    Beginner Note:
        We use SQLAlchemy's ``add_all()`` to insert all records in a single
        database transaction. Then we commit once. This is MUCH faster than
        inserting one row at a time because it reduces round-trips to the
        database.

        Each record is checked for duplicates using the SKU ID and content
        text combination. If a record with the same SKU ID and content already
        exists, we skip it (``ON CONFLICT DO NOTHING``). This makes the
        script idempotent — running it twice produces the same result.

    Args:
        database_session: Active SQLAlchemy session.
        csv_rows: The list of rows loaded from the CSV.
        embeddings: The 768-dimensional vectors, one per CSV row.

    Returns:
        The number of new clinical knowledge records inserted.
    """
    new_records: list[ClinicalKnowledgeBase] = []
    skipped_count: int = 0

    for row_index, row in enumerate(csv_rows):
        sku_id: str = row["sku_id"]
        formatted_text: str = row["formatted_text"]
        embedding: list[float] = embeddings[row_index]

        # Check if this exact knowledge already exists in the database.
        existing_record: Optional[ClinicalKnowledgeBase] = (
            database_session.query(ClinicalKnowledgeBase)
            .filter(
                ClinicalKnowledgeBase.sku_id == sku_id,
                ClinicalKnowledgeBase.content == formatted_text,
            )
            .first()
        )

        if existing_record:
            skipped_count += 1
            continue

        # Build the metadata payload with supplementary information
        # that the frontend can display alongside search results.
        metadata_payload: dict = {
            "brand_name": row.get("brand_name", ""),
            "generic_name": row.get("generic_name", ""),
            "price_inr": row.get("price_inr", ""),
            "indications": row.get("indications", ""),
            "side_effects": row.get("side_effects", ""),
            "contraindications": row.get("contraindications", ""),
        }

        new_record: ClinicalKnowledgeBase = ClinicalKnowledgeBase(
            sku_id=sku_id,
            content=formatted_text,
            embedding=embedding,
            metadata_payload=metadata_payload,
        )
        new_records.append(new_record)

    # Bulk-insert all new records in a single transaction.
    # This is dramatically faster than individual INSERT statements.
    if new_records:
        database_session.add_all(new_records)
        database_session.commit()
        logger.info(
            "Inserted %d new clinical knowledge records. Skipped %d duplicates.",
            len(new_records),
            skipped_count,
        )
    else:
        logger.info("No new records to insert. All %d records already exist.", skipped_count)

    return len(new_records)


def main() -> None:
    """
    Main entry point for the bulk ingestion pipeline.

    Beginner Note:
        This function orchestrates the entire ingestion flow. Each step is
        clearly separated so you can see exactly what happens in order:
        1. Detect hardware (GPU vs CPU).
        2. Load the AI model.
        3. Read the CSV file.
        4. Create parent medication records.
        5. Generate vector embeddings in batches.
        6. Insert everything into the database.
    """
    print("=" * 72)
    print("  GPU-ACCELERATED BULK CLINICAL KNOWLEDGE INGESTION ENGINE")
    print("=" * 72)

    # ======================================================================
    # STAGE 1: Hardware Detection
    # ======================================================================
    # We check if this machine has an NVIDIA GPU before loading the model.
    device: str = detect_device()

    # ======================================================================
    # STAGE 2: Load the AI Model
    # ======================================================================
    # PubMedBERT converts clinical text into 768-dimensional vectors that
    # the pgvector search engine can compare using cosine distance.
    model = load_model(device=device)

    # ======================================================================
    # STAGE 3: Read the CSV File
    # ======================================================================
    # Load all rows from the Indian Essential Medicines CSV into memory.
    csv_rows: list[dict] = read_csv_rows(csv_path=CSV_FILE_PATH)

    if not csv_rows:
        logger.error("No rows found in CSV file. Aborting.")
        sys.exit(1)

    # ======================================================================
    # STAGE 4: Create Parent Medication Records
    # ======================================================================
    # The clinical_knowledge_base table has a foreign key constraint that
    # references medications(sku_id). We must create parent rows first.
    db_session: Session = SessionLocal()
    try:
        ensure_parent_medications_exist(
            database_session=db_session,
            csv_rows=csv_rows,
        )

        # ==================================================================
        # STAGE 5: Generate Vector Embeddings (GPU-accelerated, batched)
        # ==================================================================
        # Extract the formatted text from each CSV row.
        all_texts: list[str] = [row["formatted_text"] for row in csv_rows]

        logger.info(
            "Starting batch embedding generation. Batch size: %d, Device: %s.",
            BATCH_SIZE,
            device,
        )
        all_embeddings: list[list[float]] = batch_generate_embeddings(
            model=model,
            texts=all_texts,
            batch_size=BATCH_SIZE,
            device=device,
        )

        # ==================================================================
        # STAGE 6: Bulk Insert into Clinical Knowledge Base
        # ==================================================================
        # Now that we have all embeddings, insert them into the database
        # alongside the original text content.
        inserted_count: int = bulk_insert_knowledge(
            database_session=db_session,
            csv_rows=csv_rows,
            embeddings=all_embeddings,
        )

        # ==================================================================
        # SUMMARY
        # ==================================================================
        print("=" * 72)
        print("  INGESTION COMPLETE")
        print("=" * 72)
        print(f"  CSV rows loaded:     {len(csv_rows)}")
        print(f"  Embeddings generated: {len(all_embeddings)}")
        print(f"  Records inserted:     {inserted_count}")
        print(f"  Vector dimensions:    {EMBEDDING_DIMENSIONS}")
        print(f"  Device used:          {device}")
        print("=" * 72)

    except Exception as error:
        db_session.rollback()
        logger.error("Ingestion failed. Database rolled back. Error: %s", error)
        raise
    finally:
        db_session.close()


if __name__ == "__main__":
    main()
