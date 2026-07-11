"""
Clinical Knowledge Base Seeding Script.

Beginner Note: This standalone script populates the clinical_knowledge_base
table with foundational drug safety documents. It generates 768-dimensional
vector embeddings using a deterministic hash (not PubMedBERT directly) so the
script runs on machines without the full ML stack installed.

In production, re-embed with the real PubMedBERT model by running:
    python -c "from app.workers.embedding_tasks import generate_and_store_embedding; generate_and_store_embedding('SKU-ID', 'content')"

The tsvector column (content_fts) IS auto-populated by PostgreSQL because it
is defined as GENERATED ALWAYS AS to_tsvector('english', content).

Usage:
    python scripts/seed_clinical_data.py

Safe to run multiple times in development (will create duplicates).
"""

import os
import sys
import hashlib
import math
import logging

# Add parent directory to sys.path so we can import the app's modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgrespassword@localhost:5432/sentinel_db",
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def deterministic_embedding(text: str, dimensions: int = 768) -> list[float]:
    """
    Generate a deterministic 768-dimensional vector from text content.

    Beginner Note: In production, this should be replaced with a real
    PubMedBERT embedding (768 dimensions) for accurate semantic search.
    However, the actual model loading (sentence_transformers) requires
    a full PyTorch/TorchAudio installation that is not available on
    all development machines.

    This fallback uses SHA-256 to seed a deterministic random generator
    for each text chunk, producing unit-normalized vectors. While not
    semantically meaningful, it allows the vector search pipeline to
    function during development and testing.

    To generate proper embeddings after deployment:
        pip install sentence-transformers
        python -c "
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer('pritamdeka/S-PubMedBert-MSN-ME')
    emb = model.encode('your text here').tolist()
    print(emb)
    "
    """
    # Use SHA-256 hash of the text to seed a deterministic RNG
    hash_bytes = hashlib.sha256(text.encode("utf-8")).digest()

    # Generate random floats using the hash as seed
    random_values = []
    for i in range(dimensions):
        # Create a unique seed for each dimension using hash + position
        dimension_hash = hashlib.sha256(
            hash_bytes + str(i).encode("utf-8")
        ).digest()
        # Convert the first 4 bytes of the hash to a float in [0, 1)
        int_value = int.from_bytes(dimension_hash[:4], "big")
        random_values.append(int_value / (2**32))

    # Normalize to unit length (L2 norm = 1) so cosine distance is meaningful
    magnitude = math.sqrt(sum(v * v for v in random_values))
    normalized = [v / magnitude for v in random_values]

    return normalized


# =========================================================================
# CLINICAL KNOWLEDGE DOCUMENTS
# =========================================================================
# Each document represents a real-world clinical guideline that a pharmacist
# might query during a consultation. The content MUST be factually accurate
# as it will be passed through the RAG pipeline's "Do Not Hallucinate" prompt.
#
# We store 3 foundational documents covering common pharmacy queries:
#   1. Dolo-650 (Paracetamol) — pain/fever, the most common OTC query
#   2. Amoxicillin — antibiotic, requires allergy screening
#   3. Sildenafil (Viagra) — cross-sell with condoms, nitrate contraindication

# =========================================================================
# PARENT SKU DEFINITIONS (Medications table)
# =========================================================================
# Beginner Note: The clinical_knowledge_base table has a FOREIGN KEY
# constraint linking sku_id -> medications.sku_id. This means PostgreSQL
# will REJECT any clinical record whose sku_id does not already exist in
# the medications table. We MUST insert the parent rows first.
#
# This is a fundamental relational database concept:
#   PARENT TABLE: medications  (the "anchor" record)
#   CHILD TABLE:  clinical_knowledge_base  (additional details about the medication)
#
# You cannot have a child without a parent. Attempting to insert a child
# row with a non-existent parent sku_id causes an IntegrityError.

PARENT_MEDICATIONS = [
    {
        "sku_id": "DOLO-650",
        "apis": ["Paracetamol", "Acetaminophen"],
        "therapeutic_classes": ["Analgesic", "Antipyretic", "NSAID Alternative"],
        "cdsco_schedule": "OTC",  # Over-The-Counter in India
    },
    {
        "sku_id": "AMOXI-500",
        "apis": ["Amoxicillin"],
        "therapeutic_classes": ["Antibiotic", "Penicillin-class", "Broad-spectrum"],
        "cdsco_schedule": "Schedule H",  # Prescription-only antibiotic
    },
    {
        "sku_id": "SILD-50",
        "apis": ["Sildenafil Citrate"],
        "therapeutic_classes": ["PDE5 Inhibitor", "Vasodilator"],
        "cdsco_schedule": "Schedule H",  # Prescription-only
    },
]


CLINICAL_DOCUMENTS = [
    {
        "sku_id": "DOLO-650",
        "content": (
            "Dolo-650 (Paracetamol / Acetaminophen) is a non-opioid analgesic "
            "and antipyretic used for mild-to-moderate pain and fever. "
            "INDICATIONS: Fever, headache, muscle aches, toothache, osteoarthritis pain. "
            "DOSAGE: Adults — 500mg to 1000mg every 4-6 hours as needed, "
            "max 4000mg in 24 hours. Do not exceed 4000mg/day due to risk of "
            "hepatotoxicity. Children — dosage based on weight (10-15mg/kg every 4-6 hours). "
            "SAFETY: Generally safe during pregnancy (FDA Category B) and breastfeeding. "
            "CONTRAINDICATIONS: Severe hepatic impairment, active liver disease, "
            "known hypersensitivity to Paracetamol. "
            "WARNING: Alcohol consumption increases risk of liver damage. "
            "Do not combine with other Paracetamol-containing medications."
        ),
    },
    {
        "sku_id": "AMOXI-500",
        "content": (
            "Amoxicillin 500mg is a broad-spectrum penicillin-class antibiotic "
            "used for bacterial infections. "
            "INDICATIONS: Respiratory tract infections (bronchitis, pneumonia), "
            "ear infections (otitis media), sinusitis, urinary tract infections, "
            "skin infections, Helicobacter pylori eradication (combination therapy). "
            "DOSAGE: Adults — 500mg three times daily or 875mg twice daily for 7-14 days. "
            "Children — 20-40mg/kg/day in divided doses. "
            "CONTRAINDICATIONS: Known hypersensitivity to Penicillin or "
            "Cephalosporin antibiotics (cross-allergy risk). "
            "CAUTION: Reduce dose in renal impairment (CrCl < 30mL/min). "
            "SIDE EFFECTS: Diarrhea (most common), nausea, rash. "
            "If rash appears with fever and joint pain, assess for hypersensitivity. "
            "WARNING: Ineffective against viral infections (common cold, flu). "
            "Complete the full course even if symptoms improve."
        ),
    },
    {
        "sku_id": "SILD-50",
        "content": (
            "Sildenafil Citrate (Viagra) 50mg is a PDE5 inhibitor used for "
            "erectile dysfunction (ED). "
            "INDICATIONS: Erectile dysfunction, pulmonary arterial hypertension "
            "(at different dosing, under brand Revatio). "
            "DOSAGE: 50mg taken approximately 1 hour before sexual activity. "
            "Max 100mg per dose, max 1 dose per day. Take on empty stomach for "
            "faster absorption; high-fat meals delay onset. "
            "CONTRAINDICATIONS: Absolute contraindication with ANY nitrate "
            "medication (Nitroglycerin, Isosorbide mononitrate/dinitrate) — "
            "combination can cause fatal hypotension. "
            "Also contraindicated with Riociguat, severe hepatic impairment, "
            "severe hypotension (BP < 90/50). "
            "WARNING: Priapism risk (erection lasting > 4 hours) requires "
            "immediate medical attention. Sudden vision or hearing loss reported. "
            "CROSS-SELL NOTE: Often prescribed alongside Condoms for safer "
            "sexual health. Consider recommending STI screening. "
            "ONSET: 30-60 minutes, lasting 4 hours."
        ),
    },
]


def ensure_parent_medications_exist(db) -> int:
    """
    Insert parent medication SKUs if they do not already exist.

    Beginner Note: The clinical_knowledge_base table has a foreign key
    (sku_id) that references medications.sku_id. Before we can insert
    clinical documents, the corresponding SKU must exist in the medications
    table. This function checks each SKU and creates it if missing.

    This is called the "Parent-First" pattern — always ensure the parent
    table has the required rows before inserting into the child table.

    Returns the number of parent rows created (0 if all already existed).
    """
    from app.infrastructure.models import MedicationModel

    parents_created = 0

    for med_data in PARENT_MEDICATIONS:
        sku = med_data["sku_id"]

        # Check if the parent SKU already exists in the medications table
        existing_medication = db.query(MedicationModel).filter(
            MedicationModel.sku_id == sku
        ).first()

        if existing_medication:
            # Parent record already exists — no need to create it again
            logger.info(f"Parent SKU {sku} already exists in medications table.")
        else:
            # Parent record is missing — insert it now to satisfy FK constraint
            logger.info(f"Creating parent SKU {sku} in medications table...")

            new_medication = MedicationModel(
                sku_id=sku,
                apis=med_data["apis"],
                therapeutic_classes=med_data["therapeutic_classes"],
                cdsco_schedule=med_data["cdsco_schedule"],
            )
            db.add(new_medication)
            db.flush()
            parents_created += 1
            logger.info(
                f"Created parent SKU {sku} with "
                f"apis={med_data['apis']}, "
                f"schedule={med_data['cdsco_schedule']}."
            )

    db.commit()
    logger.info(f"Parent medication check complete. Created {parents_created} new SKU(s).")
    return parents_created


def seed_clinical_knowledge_base() -> int:
    """Insert all clinical documents into the database with vector embeddings.

    Returns the number of rows inserted.
    """
    from sqlalchemy.orm import Session
    from app.infrastructure.database import SessionLocal
    from app.infrastructure.models import ClinicalKnowledgeBase

    db: Session = SessionLocal()
    rows_inserted = 0

    try:
        # ==================================================================
        # PARENT-FIRST: Ensure medications exist before clinical records
        # ==================================================================
        # The foreign key constraint (clinical_knowledge_base_sku_id_fkey)
        # will reject any insert where the sku_id does not exist in the
        # medications table. We must guarantee parent records exist FIRST.
        ensure_parent_medications_exist(db)

        for doc in CLINICAL_DOCUMENTS:
            logger.info(
                f"Processing document: SKU={doc['sku_id']}, "
                f"content_length={len(doc['content'])} chars"
            )

            # Generate a deterministic 768-dimensional vector
            embedding = deterministic_embedding(doc["content"])

            # Create the ORM record.
            # Note: content_fts is GENERATED ALWAYS AS — PostgreSQL will
            # auto-populate it from the 'content' column using
            # to_tsvector('english', content). We do NOT set it manually.
            kb_entry = ClinicalKnowledgeBase(
                sku_id=doc["sku_id"],
                content=doc["content"],
                embedding=embedding,
                metadata_payload={
                    "source": "CDSCO Guidelines / Drug Label",
                    "language": "en",
                    "type": "drug_safety_monograph",
                },
            )

            db.add(kb_entry)
            db.flush()
            rows_inserted += 1

            logger.info(f"Inserted id={kb_entry.id} for SKU={doc['sku_id']}")

        db.commit()
        logger.info(f"Committed {rows_inserted} rows.")

    except Exception as error:
        db.rollback()
        logger.error(f"Seeding failed, rolled back: {error}")
        raise

    finally:
        db.close()

    return rows_inserted


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("CLINICAL KNOWLEDGE BASE SEEDING")
    logger.info("=" * 60)

    count = seed_clinical_knowledge_base()

    logger.info(f"Seeding complete. {count} documents inserted.")
    print(f"\nSUCCESS: Inserted {count} clinical documents into the database.")
