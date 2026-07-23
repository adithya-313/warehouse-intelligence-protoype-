"""
Step 5.2e: Generic Clinical Knowledge Ingestion Engine
=======================================================

Beginner Note — WHY this script exists:
    Up until now, our clinical_knowledge_base table had only 11 rows — the
    original hand-curated medicines. We have 1,585 unique Indian generic
    drugs we want to support, each with OpenFDA-sourced clinical information
    (dosage, warnings, pregnancy guidance, interactions, etc.).

    This script connects three separate data sources that have been prepared
    in previous steps:

      Layer 1 — data/indian_pharmaceutical_products_clean.csv
          The raw, 253,973-row dataset of every branded pharmaceutical product
          sold in India. We use this to discover every real brand name for
          each of our 1,585 generics.

      Layer 2 — data/staging/openfda_full_results_corrected.jsonl
          The OpenFDA lookup results (one record per generic). This tells us
          whether FDA data is available, and if so, provides pharmacological
          classifications.

      Staging list — data/staging/unique_generics.csv
          The 1,585 deduplicated normalized generic names that define the
          scope of what we need to insert.

    The output of this script is three populated database tables:
      - medications: one new "GENERIC_REF_*" row per generic
      - clinical_knowledge_base: one embedding row per generic
      - drug_brand_aliases: all known brand names per generic (for fuzzy search)

HOW TO RUN:
    Inside the docker container:
        docker compose exec api python scripts/ingest_generics_52e.py

    The script is fully resumable. If it crashes mid-way, re-run it and it
    will skip generics that were already fully processed (idempotent by design).
"""

import csv
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

# Import our existing application infrastructure so we stay consistent with
# the running application's session management, connection strings, and ORM models.
from app.infrastructure.database import SessionLocal
from app.infrastructure.models import (
    ClinicalKnowledgeBase,
    DrugBrandAlias,
    MedicationModel,
)

# ---------------------------------------------------------------------------
# LOGGING SETUP
# We log to the console with timestamps so the developer can see exactly
# which stage is running and how long it takes.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CONFIGURATION — file paths relative to the project root
# ---------------------------------------------------------------------------
LAYER1_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "indian_pharmaceutical_products_clean.csv",
)

OPENFDA_JSONL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "staging",
    "openfda_full_results_corrected.jsonl",
)

UNIQUE_GENERICS_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "staging",
    "unique_generics.csv",
)

# The prefix we prepend to every sku_id we create. This makes it visually
# obvious that these are reference generics, not real inventory items.
GENERIC_SKU_PREFIX = "GENERIC_REF_"

# Batch size for GPU embedding. 128 fits safely in 8GB VRAM.
# On CPU, smaller batches (32) reduce memory pressure at cost of more overhead.
BATCH_SIZE = 128


# ---------------------------------------------------------------------------
# STEP 0 HELPER — Normalize generic name
# ---------------------------------------------------------------------------

def normalize_generic_name(raw_name: str) -> str:
    """
    WHY THIS EXISTS:
        The same drug appears in the Layer 1 CSV under many slightly different
        spellings: "Amoxycillin 500mg", "AMOXYCILLIN", "Amoxycillin Trihydrate".
        We need a single canonical key for each drug so we can reliably group
        brand names under the correct generic. This function strips doses,
        units, and normalizes case so "Amoxycillin 500mg" and "amoxycillin"
        both reduce to the same string: "amoxycillin".

        IMPORTANT: This must be the EXACT same function used in step 5.2c when
        unique_generics.csv was originally built — otherwise our keys won't match.
    """
    if not isinstance(raw_name, str):
        return ""

    # Lowercase everything first — "Paracetamol" and "paracetamol" are the same drug.
    normalized = raw_name.lower()

    # Remove embedded dosage numbers and units like "500mg", "250 mg", "0.5% w/v".
    # These appear in the raw ingredient column and would break grouping if left in.
    unit_pattern = r'\b\d+(?:\.\d+)?\s*(?:mg|g|mcg|ml|%|w/w|w/v|iu)(?:/\d*\s*(?:mg|g|mcg|ml|%|w/w|w/v|iu))?\b'
    normalized = re.sub(unit_pattern, '', normalized)

    # Clean up any empty parentheses left behind by the dosage removal (e.g. "(  )" -> "").
    normalized = re.sub(r'\(\s*\)', '', normalized)

    # Strip leading/trailing whitespace and collapse multiple internal spaces into one.
    normalized = normalized.strip()
    normalized = re.sub(r'\s+', ' ', normalized)

    return normalized


# ---------------------------------------------------------------------------
# STEP 1 — Build full brand alias map
# ---------------------------------------------------------------------------

def build_brand_alias_map_from_layer1(layer1_csv_path: str) -> dict[str, set[str]]:
    """
    WHY THIS EXISTS:
        The unique_generics.csv (our 1,585-row staging list) only kept ONE
        sample brand name per generic — just enough to identify the drug.
        But for drug_brand_aliases, we want EVERY real brand name that maps
        to each generic, so that a pharmacist who types "Dolo" or "Calpol"
        or "Metacin" can all find Paracetamol.

        We rebuild this map here by scanning ALL 253,973 rows of the original
        Layer 1 CSV and grouping brand names by their normalized generic name.

    Returns:
        A dictionary where each key is a normalized generic name (e.g.
        "paracetamol") and each value is a Python set of distinct raw brand
        name strings (e.g. {"DOLO 650", "CALPOL", "METACIN", ...}).
    """
    # We use a defaultdict(set) so we never have to check "does this key exist?"
    # before adding to it. Sets automatically deduplicate brand names.
    alias_map: dict[str, set[str]] = defaultdict(set)

    logger.info("Reading Layer 1 CSV to build brand alias map: %s", layer1_csv_path)

    with open(layer1_csv_path, mode="r", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)

        rows_read = 0
        rows_skipped_empty = 0

        for row in reader:
            raw_ingredient = row.get("primary_ingredient", "").strip()
            raw_brand_name = row.get("brand_name", "").strip()

            # Skip rows where either field is missing — we can't group them.
            if not raw_ingredient or not raw_brand_name:
                rows_skipped_empty += 1
                continue

            normalized_key = normalize_generic_name(raw_ingredient)

            # Skip if normalization produced an empty string (shouldn't happen
            # but we guard against it to avoid inserting empty keys into the map).
            if not normalized_key:
                rows_skipped_empty += 1
                continue

            # Store the raw brand name uppercased for consistent matching later.
            alias_map[normalized_key].add(raw_brand_name.upper())
            rows_read += 1

    total_pairs = sum(len(brands) for brands in alias_map.values())
    logger.info(
        "Brand alias map built. %d rows processed, %d skipped. "
        "%d unique generics, %d total (generic, brand) pairs.",
        rows_read,
        rows_skipped_empty,
        len(alias_map),
        total_pairs,
    )

    return alias_map


# ---------------------------------------------------------------------------
# STEP 2 HELPER — Build the clinical content text for one generic
# ---------------------------------------------------------------------------

def build_content_text_for_generic(
    normalized_generic_name: str,
    openfda_record: dict,
    known_brand_names: set[str],
) -> tuple[str, str]:
    """
    WHY THIS EXISTS:
        The embedding model turns text into a vector number. The QUALITY of
        that text directly determines how useful the search results will be.
        For generics with FDA data, we want to embed the actual pharmacological
        details. For generics with no FDA data (not approved in the USA), we
        can't fake clinical details — we build an honest "identity card" instead
        that at minimum tells the search engine what this drug is and what it
        treats (from its therapeutic class).

        The returned text is what gets stored in clinical_knowledge_base.content
        and embedded by PubMedBERT.

    Returns:
        A tuple of (content_text, data_quality_label).
        data_quality_label will be one of:
          "single_ingredient" — clean single-drug FDA data
          "combination_product" — FDA data from a multi-drug combo product
          "identity_only" — no FDA data available
    """
    status = openfda_record.get("status", "NO_FDA_DATA")
    data_quality = openfda_record.get("data_quality")
    matched_name = openfda_record.get("matched_openfda_name", "")
    raw_block = openfda_record.get("raw_openfda_block") or {}

    # ---- Case 1: We have FDA data ----------------------------------------
    if status == "MATCHED":

        # Build a plain-English preamble that names the drug clearly.
        drug_identity_line = (
            f"Drug: {normalized_generic_name.upper()}"
        )
        if matched_name:
            drug_identity_line += f" (FDA name: {matched_name})"

        # Extract pharmacological class if available. OpenFDA stores this in
        # pharm_class_epc (Established Pharmacologic Class) as an array of strings.
        pharm_class_strings = raw_block.get("pharm_class_epc", [])
        therapeutic_class_line = ""
        if pharm_class_strings:
            # Strip the "[EPC]" or "[MoA]" suffix that OpenFDA appends.
            clean_classes = [c.replace("[EPC]", "").replace("[MoA]", "").strip() for c in pharm_class_strings]
            therapeutic_class_line = f"\n\nTherapeutic Class: {'; '.join(clean_classes)}"

        # Extract mechanism of action if available.
        moa_strings = raw_block.get("pharm_class_moa", [])
        moa_line = ""
        if moa_strings:
            clean_moa = [c.replace("[MoA]", "").strip() for c in moa_strings]
            moa_line = f"\n\nMechanism of Action: {'; '.join(clean_moa)}"

        # Extract routes of administration (e.g. "ORAL", "TOPICAL").
        route_strings = raw_block.get("route", [])
        route_line = ""
        if route_strings:
            route_line = f"\n\nRoutes of Administration: {', '.join(route_strings)}"

        # Include known brand names from Layer 1 so the embedding carries
        # brand-name context (helps with "tell me about Zifi" type questions).
        sample_brands = sorted(list(known_brand_names))[:20]  # cap at 20 to avoid huge text
        brand_line = ""
        if sample_brands:
            brand_line = f"\n\nKnown Indian Brand Names (sample): {', '.join(sample_brands)}"

        # For combination products, prepend a clear disclaimer. This matters
        # because dosage and interaction data from a combo product (e.g. Augmentin =
        # amoxicillin + clavulanate) can NOT be directly applied to just amoxicillin.
        if data_quality == "combination_product":
            disclaimer = (
                "NOTE: The following clinical data is sourced from a COMBINATION product "
                f"containing this ingredient alongside others (FDA product: {matched_name}), "
                "not this ingredient alone. Dosage and interaction specifics may not directly "
                "apply to a single-ingredient formulation."
            )
            content = (
                f"{disclaimer}\n\n"
                f"{drug_identity_line}"
                f"{therapeutic_class_line}"
                f"{moa_line}"
                f"{route_line}"
                f"{brand_line}"
            )
            return content.strip(), "combination_product"

        else:
            # Clean single-ingredient FDA data — the ideal case.
            content = (
                f"{drug_identity_line}"
                f"{therapeutic_class_line}"
                f"{moa_line}"
                f"{route_line}"
                f"{brand_line}"
            )
            return content.strip(), "single_ingredient"

    # ---- Case 2: No FDA data at all ----------------------------------------
    else:
        # This drug is not approved for marketing in the United States.
        # We cannot fabricate clinical details. Instead, we build an honest
        # "identity card" using the brand names from Layer 1 (which tell us
        # this drug IS used in India, just not in the US).
        disclaimer = (
            "FDA clinical monograph data (dosage, pregnancy/pediatric guidance, interactions) "
            f"is not available for {normalized_generic_name.upper()} — it is not currently "
            "approved for marketing in the United States. Please verify dosing against Indian "
            "prescribing references before use."
        )

        # Even without FDA data, we can note the brand names. A pharmacist
        # searching "Domperidone" or "Domstal" should still find this entry.
        sample_brands = sorted(list(known_brand_names))[:20]
        brand_line = ""
        if sample_brands:
            brand_line = f"\n\nKnown Indian Brand Names (sample): {', '.join(sample_brands)}"

        content = (
            f"Drug: {normalized_generic_name.upper()}\n\n"
            f"{disclaimer}"
            f"{brand_line}"
        )
        return content.strip(), "identity_only"


# ---------------------------------------------------------------------------
# STEP 3 — Load OpenFDA lookup results into a fast in-memory dictionary
# ---------------------------------------------------------------------------

def load_openfda_lookup_index(jsonl_path: str) -> dict[str, dict]:
    """
    WHY THIS EXISTS:
        The openfda_full_results_corrected.jsonl file has 1,585 records,
        one per normalized generic name. For the per-generic loop in Step 4,
        we need to look up a generic's record instantly without scanning the
        file each time. Loading it into a Python dict gives us O(1) lookups.

    Returns:
        A dict keyed by normalized_generic_name, value is the full record dict.
    """
    index: dict[str, dict] = {}

    logger.info("Loading OpenFDA lookup index from: %s", jsonl_path)

    with open(jsonl_path, mode="r", encoding="utf-8") as jsonl_file:
        for line in jsonl_file:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            key = record.get("normalized_generic_name", "")
            if key:
                index[key] = record

    logger.info("OpenFDA index loaded. %d records available.", len(index))
    return index


# ---------------------------------------------------------------------------
# STEP 4 — Load the 1585 target generics from unique_generics.csv
# ---------------------------------------------------------------------------

def load_target_generics(unique_generics_csv_path: str) -> list[str]:
    """
    WHY THIS EXISTS:
        unique_generics.csv is the single authoritative list of what we need
        to ingest. It was built in step 5.2c by deduplicating all 253,973 rows
        in Layer 1. Loading it separately (rather than deriving it from Layer 1
        again) ensures we use EXACTLY the same 1,585 names that all prior steps
        were built around — no drift.

    Returns:
        A list of normalized_generic_name strings in the order they appear in the CSV.
    """
    generics: list[str] = []

    with open(unique_generics_csv_path, mode="r", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            name = row.get("normalized_generic_name", "").strip()
            if name:
                generics.append(name)

    logger.info("Loaded %d target generics from unique_generics.csv.", len(generics))
    return generics


# ---------------------------------------------------------------------------
# STEP 5 — Load the embedding model ONCE before the per-generic loop
# ---------------------------------------------------------------------------

def load_embedding_model():
    """
    WHY THIS EXISTS:
        Loading PubMedBERT takes several seconds and downloads a 400MB model
        file. If we loaded it inside the per-generic loop, it would reload
        1,585 times — taking hours. We load it ONCE here and pass the model
        object into the loop as a reusable tool.

    Returns:
        A tuple of (model, device_string).
        model is a SentenceTransformer ready to encode() text.
        device_string is "cuda" or "cpu" for logging.
    """
    import torch
    from sentence_transformers import SentenceTransformer

    # Detect whether a GPU is available. Using CUDA means embedding 1585 texts
    # in seconds instead of minutes.
    if torch.cuda.is_available():
        device_name = torch.cuda.get_device_name(0)
        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        logger.info("GPU detected: %s (%.1f GB VRAM). Using CUDA acceleration.", device_name, vram_gb)
        device = "cuda"
    else:
        logger.warning("No GPU detected. Using CPU. Expect ~30-60 seconds for 1585 embeddings.")
        device = "cpu"

    logger.info("Loading PubMedBERT model (NeuML/pubmedbert-base-embeddings)...")
    model = SentenceTransformer("NeuML/pubmedbert-base-embeddings", device=device)
    logger.info("Model loaded successfully on %s.", device)

    return model, device


# ---------------------------------------------------------------------------
# STEP 6 — Generate all embeddings in one batched pass
# ---------------------------------------------------------------------------

def generate_all_embeddings_in_batch(
    model,
    all_content_texts: list[str],
    batch_size: int,
) -> list[list[float]]:
    """
    WHY THIS EXISTS:
        GPUs are efficient at processing many items in parallel. Rather than
        embedding one text at a time (which would waste 99% of the GPU's
        capacity), we group texts into batches and encode each batch together.
        This alone provides a 50-100x speedup on GPU compared to per-item encoding.

    Args:
        model: The loaded SentenceTransformer model.
        all_content_texts: All 1585 texts to embed, in the same order as our generics list.
        batch_size: How many texts to encode per GPU pass (128 is safe for 8GB VRAM).

    Returns:
        A list of 768-dimensional float vectors, one per input text, in the same order.
    """
    from tqdm import tqdm

    all_embeddings: list[list[float]] = []
    total_texts = len(all_content_texts)

    logger.info("Starting batch embedding. %d texts, batch size %d.", total_texts, batch_size)
    embedding_start_time = time.time()

    # Process texts in chunks so we never overflow GPU memory.
    for batch_start in tqdm(range(0, total_texts, batch_size), desc="Embedding batches", unit="batch"):
        batch_end = min(batch_start + batch_size, total_texts)
        batch_texts = all_content_texts[batch_start:batch_end]

        # model.encode() returns a numpy array of shape (len(batch), 768).
        # .tolist() converts each row to a plain Python list of floats that
        # SQLAlchemy's pgvector column can store.
        batch_embeddings = model.encode(
            batch_texts,
            batch_size=batch_size,
            show_progress_bar=False,
        ).tolist()

        all_embeddings.extend(batch_embeddings)

    embedding_total_seconds = time.time() - embedding_start_time
    logger.info(
        "Embedding complete. %d vectors generated in %.1f seconds.",
        len(all_embeddings),
        embedding_total_seconds,
    )

    return all_embeddings, embedding_total_seconds


# ---------------------------------------------------------------------------
# STEP 7 — The per-generic insert loop (atomic per generic, resumable)
# ---------------------------------------------------------------------------

def ingest_one_generic(
    database_session: Session,
    normalized_generic_name: str,
    content_text: str,
    data_quality_label: str,
    embedding_vector: list[float],
    brand_aliases: set[str],
) -> bool:
    """
    WHY THIS EXISTS:
        We want each generic's data to be inserted atomically — meaning either
        ALL three tables (medications, clinical_knowledge_base, drug_brand_aliases)
        get their rows, or NONE of them do (on failure, we roll back). This
        prevents half-inserted records that could confuse the resolver.

        Wrapping each generic in its own try/except/rollback means one bad generic
        (e.g. a brand name that's too long) won't abort the other 1,584 generics.

    Returns:
        True if the insert succeeded, False if it failed (after rollback).
    """
    # Build the SKU ID for this generic. We uppercase the normalized name so it's
    # easier to read in the database (e.g. "GENERIC_REF_PARACETAMOL").
    generic_sku_id = f"{GENERIC_SKU_PREFIX}{normalized_generic_name.upper()}"

    try:
        # ---- a) Insert into medications -----------------------------------
        # This row MUST be created before clinical_knowledge_base because
        # clinical_knowledge_base.sku_id is a foreign key referencing medications.sku_id.
        new_medication = MedicationModel(
            sku_id=generic_sku_id,
            apis=[normalized_generic_name],           # List format required by ARRAY(Text) column
            therapeutic_classes=["General Reference"],  # Placeholder — no curator has reviewed
            cdsco_schedule="UNKNOWN",                 # We don't know Indian regulatory status
            pregnancy_category=None,                  # Honestly NULL — not yet curated
            pediatric_age_threshold_months=None,      # Honestly NULL — not yet curated
            interaction_matrix=None,                  # Honestly NULL — not yet curated
            is_approved_by_curator=False,             # These are reference rows, not vetted stock
        )
        database_session.add(new_medication)

        # We flush (but do NOT commit yet) so PostgreSQL assigns the row internally
        # and the foreign key from clinical_knowledge_base can reference it.
        database_session.flush()

        # ---- b) Insert into clinical_knowledge_base -----------------------
        # The metadata_payload carries structured fields the frontend can use
        # to display source information alongside search results.
        metadata_payload = {
            "generic_name": normalized_generic_name,
            "data_quality": data_quality_label,
            "source": "openfda_generic_reference",
        }

        new_knowledge_entry = ClinicalKnowledgeBase(
            sku_id=generic_sku_id,
            content=content_text,
            embedding=embedding_vector,
            metadata_payload=metadata_payload,
        )
        database_session.add(new_knowledge_entry)

        # ---- c) Bulk insert into drug_brand_aliases -----------------------
        # We build a flat list of dictionaries that bulk_insert_mappings can
        # use to issue a single fast multi-row INSERT statement, rather than
        # hundreds of individual INSERT calls (which would be much slower
        # at 80k+ rows across all generics).
        alias_rows = []

        # First, add one alias row for the generic name itself.
        # This means a pharmacist who types "paracetamol" can still find the record
        # even if the resolver searches via the alias table.
        alias_rows.append({
            "sku_id": generic_sku_id,
            "alias_text": normalized_generic_name.upper(),
            "alias_type": "generic_name",
        })

        # Then, add one alias row for each of the known brand names from Layer 1.
        for brand_name in brand_aliases:
            alias_rows.append({
                "sku_id": generic_sku_id,
                "alias_text": brand_name.upper(),  # Already uppercased in build_brand_alias_map
                "alias_type": "brand_name",
            })

        # bulk_insert_mappings bypasses ORM overhead and issues a direct fast INSERT.
        # This is the pattern already used in data_generator.py for TelemetryModel.
        database_session.bulk_insert_mappings(DrugBrandAlias, alias_rows)

        # ---- d) Commit all three inserts together atomically ---------------
        # If we reach this line, all three parts succeeded. Committing now makes
        # all changes permanent. If the commit itself fails, the except block below
        # handles the rollback.
        database_session.commit()

        return True

    except Exception as insert_error:
        # Something went wrong for this specific generic. Roll back ONLY this
        # generic's changes — the previous generics' commits are unaffected.
        database_session.rollback()
        logger.error(
            "FAILED to insert generic '%s' (sku_id: %s). Error: %s. Rolling back and continuing.",
            normalized_generic_name,
            generic_sku_id,
            insert_error,
        )
        return False


# ---------------------------------------------------------------------------
# MAIN — orchestrate the full pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    """
    WHY THIS EXISTS:
        This function is the director of the entire pipeline. It calls each
        helper function in the correct order, passes results between them,
        and produces the final summary report. Reading this function top to
        bottom gives a complete overview of what this script does.
    """
    total_start_time = time.time()

    print("=" * 72)
    print("  5.2e: GENERIC CLINICAL KNOWLEDGE INGESTION ENGINE")
    print("=" * 72)

    # ==========================================================================
    # PHASE 1: Load all input data sources into memory
    # ==========================================================================
    # We load everything before opening any database connections so that
    # a missing file fails fast, not halfway through writing the DB.

    logger.info("Phase 1: Loading input data sources...")

    # Load the 1585 target generics (the authoritative scope of this ingestion).
    target_generics = load_target_generics(UNIQUE_GENERICS_CSV_PATH)

    # Load the OpenFDA lookup results as a fast dictionary.
    openfda_index = load_openfda_lookup_index(OPENFDA_JSONL_PATH)

    # Build the full brand alias map from Layer 1 (every brand name per generic).
    brand_alias_map = build_brand_alias_map_from_layer1(LAYER1_CSV_PATH)

    # Report the total brand alias coverage (Step 1 output).
    total_alias_pairs = sum(len(aliases) for aliases in brand_alias_map.values())
    logger.info(
        "Total (generic, brand) alias pairs from Layer 1: %d across %d generics.",
        total_alias_pairs,
        len(brand_alias_map),
    )

    # Show 3 sample generics with their alias counts for the report.
    sample_generics_for_report = sorted(
        brand_alias_map.items(), key=lambda kv: len(kv[1]), reverse=True
    )[:3]
    for generic_key, brands in sample_generics_for_report:
        logger.info("  Sample: '%s' has %d brand aliases", generic_key, len(brands))

    # ==========================================================================
    # PHASE 2: Build all content texts (before touching the DB or model)
    # ==========================================================================
    # We separate content construction from DB writes so that a content bug
    # doesn't cause half the generics to be written before we catch the error.

    logger.info("Phase 2: Building content texts for all %d generics...", len(target_generics))

    all_content_texts: list[str] = []
    all_data_quality_labels: list[str] = []

    # Track samples for the ingestion report.
    sample_single_ingredient_text: Optional[str] = None
    sample_combination_product_text: Optional[str] = None
    sample_no_fda_text: Optional[str] = None
    sample_single_name: Optional[str] = None
    sample_combo_name: Optional[str] = None
    sample_nofda_name: Optional[str] = None

    for generic_name in target_generics:
        # Find the OpenFDA record for this generic. If it's somehow missing
        # from the index (shouldn't happen, but we guard against it), we treat
        # it as having no FDA data.
        openfda_record = openfda_index.get(generic_name, {"status": "NO_FDA_DATA"})

        # Get the brand aliases we found for this generic in Layer 1.
        known_brands = brand_alias_map.get(generic_name, set())

        content_text, data_quality_label = build_content_text_for_generic(
            normalized_generic_name=generic_name,
            openfda_record=openfda_record,
            known_brand_names=known_brands,
        )

        all_content_texts.append(content_text)
        all_data_quality_labels.append(data_quality_label)

        # Capture representative samples for the report (first of each type).
        if data_quality_label == "single_ingredient" and sample_single_ingredient_text is None:
            sample_single_ingredient_text = content_text
            sample_single_name = generic_name
        if data_quality_label == "combination_product" and sample_combination_product_text is None:
            sample_combination_product_text = content_text
            sample_combo_name = generic_name
        if data_quality_label == "identity_only" and sample_no_fda_text is None:
            sample_no_fda_text = content_text
            sample_nofda_name = generic_name

    logger.info("Content texts built. Summary by type:")
    from collections import Counter
    label_counts = Counter(all_data_quality_labels)
    for label, count in label_counts.items():
        logger.info("  %s: %d generics", label, count)

    # ==========================================================================
    # PHASE 3: Idempotency pre-check
    # ==========================================================================
    # Before touching the model or writing anything, identify which generics
    # are already in the database from a previous run. This makes the script
    # safely resumable: if it was interrupted at generic #800, re-running it
    # skips generics 1-800 and continues from #801.

    logger.info("Phase 3: Checking which generics are already in the DB (idempotency)...")

    db_session: Session = SessionLocal()
    already_done_names: set[str] = set()

    try:
        for generic_name in target_generics:
            generic_sku_id = f"{GENERIC_SKU_PREFIX}{generic_name.upper()}"
            existing_row = (
                db_session.query(MedicationModel)
                .filter(MedicationModel.sku_id == generic_sku_id)
                .first()
            )
            if existing_row:
                already_done_names.add(generic_name)
    finally:
        # Close this pre-check session cleanly.
        db_session.close()

    skipped_as_done = len(already_done_names)
    to_process = [g for g in target_generics if g not in already_done_names]

    logger.info(
        "Idempotency check done. %d already in DB (will skip). %d to insert now.",
        skipped_as_done,
        len(to_process),
    )

    if not to_process:
        logger.info("All generics already processed. Nothing to do. Exiting.")
        return

    # ==========================================================================
    # PHASE 4: Load embedding model and generate ALL embeddings in one pass
    # ==========================================================================
    # We generate embeddings for only the generics we actually need to insert
    # (skipping already-done ones). This avoids wasting GPU time on re-embedding.

    logger.info("Phase 4: Generating embeddings for %d generics...", len(to_process))

    model, device_label = load_embedding_model()

    # Collect only the content texts for generics we are actually inserting.
    # We build a mapping from generic_name -> (content_text, data_quality, embedding_index)
    # so we can look up each embedding by position after batch generation.
    texts_to_embed = []
    generics_to_insert_in_order = []

    for generic_name in target_generics:
        if generic_name in already_done_names:
            continue
        # Find the index of this generic in target_generics to get its content text.
        idx = target_generics.index(generic_name)
        texts_to_embed.append(all_content_texts[idx])
        generics_to_insert_in_order.append(generic_name)

    all_new_embeddings, embedding_seconds = generate_all_embeddings_in_batch(
        model=model,
        all_content_texts=texts_to_embed,
        batch_size=BATCH_SIZE,
    )

    # Verify counts match (this should never fail, but we check to be safe).
    assert len(all_new_embeddings) == len(generics_to_insert_in_order), (
        f"Embedding count mismatch: {len(all_new_embeddings)} embeddings vs "
        f"{len(generics_to_insert_in_order)} generics. Something went wrong."
    )

    # ==========================================================================
    # PHASE 5: Per-generic atomic insert loop
    # ==========================================================================

    logger.info("Phase 5: Starting per-generic insert loop...")

    db_session = SessionLocal()

    inserted_count = 0
    failed_generics: list[str] = []

    try:
        for position, generic_name in enumerate(generics_to_insert_in_order):
            # Look up this generic's pre-built content and embedding.
            content_text = texts_to_embed[position]
            data_quality_label = all_data_quality_labels[target_generics.index(generic_name)]
            embedding_vector = all_new_embeddings[position]
            brand_aliases = brand_alias_map.get(generic_name, set())

            # Attempt the atomic insert for this one generic.
            success = ingest_one_generic(
                database_session=db_session,
                normalized_generic_name=generic_name,
                content_text=content_text,
                data_quality_label=data_quality_label,
                embedding_vector=embedding_vector,
                brand_aliases=brand_aliases,
            )

            if success:
                inserted_count += 1
            else:
                failed_generics.append(generic_name)

            # Progress log every 100 generics so the developer knows it's moving.
            total_done = inserted_count + len(failed_generics) + skipped_as_done
            if (position + 1) % 100 == 0 or (position + 1) == len(generics_to_insert_in_order):
                logger.info(
                    "Progress: %d/%d generics processed this run "
                    "(%d inserted, %d failed, %d skipped as already done).",
                    position + 1,
                    len(generics_to_insert_in_order),
                    inserted_count,
                    len(failed_generics),
                    skipped_as_done,
                )

    finally:
        db_session.close()

    # ==========================================================================
    # PHASE 6: Final row count verification
    # ==========================================================================

    logger.info("Phase 6: Verifying final row counts in all three tables...")

    verify_session = SessionLocal()
    try:
        from sqlalchemy import text as sa_text
        final_meds = verify_session.execute(sa_text("SELECT COUNT(*) FROM medications")).scalar()
        final_ckb = verify_session.execute(sa_text("SELECT COUNT(*) FROM clinical_knowledge_base")).scalar()
        final_aliases = verify_session.execute(sa_text("SELECT COUNT(*) FROM drug_brand_aliases")).scalar()
    finally:
        verify_session.close()

    total_elapsed_seconds = time.time() - total_start_time

    # ==========================================================================
    # FINAL REPORT
    # ==========================================================================
    print("\n" + "=" * 72)
    print("  INGESTION COMPLETE — FINAL REPORT")
    print("=" * 72)
    print(f"\nStep 1 — Brand alias rebuild:")
    print(f"  Total (generic, brand) pairs found: {total_alias_pairs:,}")
    for generic_key, brands in sample_generics_for_report:
        print(f"  Sample: '{generic_key}' has {len(brands):,} brand aliases")

    print(f"\nStep 2 — Content construction samples:")
    print(f"\n  [SINGLE INGREDIENT — '{sample_single_name}']")
    print(f"  {(sample_single_ingredient_text or 'N/A')[:500]}...")
    print(f"\n  [COMBINATION PRODUCT — '{sample_combo_name}']")
    print(f"  {(sample_combination_product_text or 'N/A')[:500]}...")
    print(f"\n  [NO FDA DATA — '{sample_nofda_name}']")
    print(f"  {(sample_no_fda_text or 'N/A')[:500]}...")

    print(f"\nStep 3 — Idempotency:")
    print(f"  Generics skipped (already in DB from prior run): {skipped_as_done}")

    print(f"\nStep 4 — Insert results:")
    print(f"  Generics successfully inserted: {inserted_count}")
    if failed_generics:
        print(f"  FAILED generics ({len(failed_generics)}):")
        for name in failed_generics:
            print(f"    - {name}")
    else:
        print(f"  Failed generics: NONE")

    print(f"\nFinal row counts (before -> after):")
    print(f"  medications:            29 -> {final_meds}")
    print(f"  clinical_knowledge_base: 11 -> {final_ckb}")
    print(f"  drug_brand_aliases:      22 -> {final_aliases}")

    print(f"\nTiming:")
    print(f"  Embedding time: {embedding_seconds:.1f}s")
    print(f"  Total script time: {total_elapsed_seconds:.1f}s")
    print("=" * 72)


if __name__ == "__main__":
    main()
