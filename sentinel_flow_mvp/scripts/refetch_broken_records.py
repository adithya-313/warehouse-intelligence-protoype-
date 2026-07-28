"""
fix(5.5-f3a): Re-fetch empty/failed OpenFDA records identified in content-completeness audit.

Only touches confirmed broken records (all sections missing, ~252 chars).
Uses the identical 4-step cascade logic from retry_failed_fetches_52e_patch2.py.
Does NOT touch the other 1,007 correctly-populated records or the 577 identity-only records.
"""

import logging
import os
import re
import time
import urllib.parse
from typing import Optional

import requests
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.infrastructure.database import SessionLocal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

GENERIC_SKU_PREFIX = "GENERIC_REF_"
REQUEST_DELAY_SECONDS = 0.35

# These are the confirmed broken records from the audit.
# Only abemaciclib had all sections missing (252 chars).
CONFIRMED_BROKEN_SKUS = {
    "abemaciclib": "GENERIC_REF_ABEMACICLIB",
}

# Alias dict — identical to retry_failed_fetches_52e_patch2.py.
KNOWN_ALIASES: dict[str, str] = {
    "paracetamol": "acetaminophen",
    "salbutamol": "albuterol",
    "adrenaline": "epinephrine",
    "noradrenaline": "norepinephrine",
    "lignocaine": "lidocaine",
    "rifampicin": "rifampin",
    "pethidine": "meperidine",
    "isoprenaline": "isoproterenol",
}


def transform_spelling(raw_name: str) -> str:
    """British → American FDA spelling — identical to patch2 script."""
    if not isinstance(raw_name, str):
        return ""
    name = raw_name.replace("sulph", "sulf")
    name = name.replace("oestr", "estr")
    name = name.replace("haem", "hem")
    name = name.replace("amoxy", "amoxi")
    return name


def make_fda_api_call(
    query_url: str,
    generic_name_for_logging: str,
    max_retries: int = 3,
) -> tuple[Optional[dict], str]:
    """
    Single FDA API call with retry/backoff.
    Identical pattern to retry_failed_fetches_52e_patch2.py.
    """
    backoff_seconds = 1.0

    for attempt in range(max_retries + 1):
        time.sleep(REQUEST_DELAY_SECONDS)

        try:
            response = requests.get(query_url, timeout=10)

            if response.status_code == 200:
                return response.json(), "SUCCESS"
            elif response.status_code == 404:
                return None, "NOT_FOUND"
            elif response.status_code == 429:
                logger.warning("'%s': Rate limited (429). Sleeping %.0fs.", generic_name_for_logging, backoff_seconds + 5.0)
                time.sleep(backoff_seconds + 5.0)
                backoff_seconds *= 2
            elif response.status_code >= 500:
                logger.warning("'%s': Server error HTTP %d (attempt %d).", generic_name_for_logging, response.status_code, attempt + 1)
                time.sleep(backoff_seconds)
                backoff_seconds *= 2
            else:
                return None, f"HTTP_{response.status_code}"

        except requests.exceptions.Timeout:
            logger.warning("'%s': Timeout (attempt %d).", generic_name_for_logging, attempt + 1)
            time.sleep(backoff_seconds)
            backoff_seconds *= 2

        except requests.exceptions.ConnectionError:
            logger.warning("'%s': Connection error (attempt %d).", generic_name_for_logging, attempt + 1)
            time.sleep(backoff_seconds)
            backoff_seconds *= 2

    return None, "MAX_RETRIES"


def evaluate_label_candidates(api_response: dict) -> tuple[Optional[dict], Optional[str], Optional[str]]:
    """
    Pick the best label from an FDA result set.
    Prefers single-ingredient labels; falls back to combo.
    Identical logic to patch2 script.
    """
    results = api_response.get("results", [])
    if not results:
        return None, None, None

    for result in results:
        openfda = result.get("openfda", {})
        generic_name_list = openfda.get("generic_name", [])
        if len(generic_name_list) == 1:
            return result, generic_name_list[0], "single_ingredient"

    first_result = results[0]
    openfda = first_result.get("openfda", {})
    generic_names = openfda.get("generic_name", openfda.get("substance_name", []))
    matched_name = generic_names[0] if generic_names else None
    return first_result, matched_name, "combination_product"


def extract_clinical_fields_from_label(full_label: dict) -> dict:
    """Extract clinical text fields from an FDA full label. Identical to patch2 script."""

    def extract_text(*field_names: str) -> str:
        for field_name in field_names:
            raw_value = full_label.get(field_name)
            if raw_value:
                if isinstance(raw_value, list):
                    combined = " ".join(str(v) for v in raw_value)
                else:
                    combined = str(raw_value)
                return re.sub(r'\s+', ' ', combined).strip()
        return ""

    return {
        "dosage_and_administration": extract_text("dosage_and_administration"),
        "pregnancy_or_breastfeeding": extract_text("pregnancy", "pregnancy_or_breast_feeding"),
        "pediatric_use": extract_text("pediatric_use"),
        "warnings": extract_text("warnings_and_cautions", "warnings", "boxed_warning"),
        "drug_interactions": extract_text("drug_interactions"),
        "contraindications": extract_text("contraindications"),
    }


def run_full_cascade_for_generic(normalized_name: str) -> tuple:
    """
    Full 4-step cascade — identical logic to retry_failed_fetches_52e_patch2.py.
    Steps: A (direct generic_name) → B (alias) → C (substance_name) → D (spelling transform).
    """
    had_any_transient_error = False

    # Step A: Direct generic name search
    encoded_name = urllib.parse.quote(f'"{normalized_name}"')
    url_a = f"https://api.fda.gov/drug/label.json?search=openfda.generic_name:{encoded_name}&limit=10"
    data_a, status_a = make_fda_api_call(url_a, normalized_name)
    if status_a == "SUCCESS":
        label, matched_name, data_quality = evaluate_label_candidates(data_a)
        if label is not None:
            logger.info("'%s': Matched on step A (direct generic_name).", normalized_name)
            return label, extract_clinical_fields_from_label(label), matched_name, data_quality
    if status_a not in ("NOT_FOUND", "SUCCESS"):
        had_any_transient_error = True

    # Step B: Known alias lookup
    us_alias = KNOWN_ALIASES.get(normalized_name)
    if us_alias:
        encoded_alias = urllib.parse.quote(f'"{us_alias}"')
        url_b = f"https://api.fda.gov/drug/label.json?search=openfda.generic_name:{encoded_alias}&limit=10"
        data_b, status_b = make_fda_api_call(url_b, normalized_name)
        if status_b == "SUCCESS":
            label, matched_name, data_quality = evaluate_label_candidates(data_b)
            if label is not None:
                logger.info("'%s': Matched on step B (alias '%s').", normalized_name, us_alias)
                return label, extract_clinical_fields_from_label(label), matched_name, data_quality
        if status_b not in ("NOT_FOUND", "SUCCESS"):
            had_any_transient_error = True

    # Step C: Substance name search
    substance_search_term = KNOWN_ALIASES.get(normalized_name, normalized_name)
    encoded_substance = urllib.parse.quote(f'"{substance_search_term}"')
    url_c = f"https://api.fda.gov/drug/label.json?search=openfda.substance_name:{encoded_substance}&limit=10"
    data_c, status_c = make_fda_api_call(url_c, normalized_name)
    if status_c == "SUCCESS":
        label, matched_name, data_quality = evaluate_label_candidates(data_c)
        if label is not None:
            logger.info("'%s': Matched on step C (substance_name).", normalized_name)
            return label, extract_clinical_fields_from_label(label), matched_name, data_quality
    if status_c not in ("NOT_FOUND", "SUCCESS"):
        had_any_transient_error = True

    # Step D: British→American spelling transform
    transformed_name = transform_spelling(normalized_name)
    if transformed_name != normalized_name:
        encoded_transformed = urllib.parse.quote(f'"{transformed_name}"')
        url_d1 = f"https://api.fda.gov/drug/label.json?search=openfda.generic_name:{encoded_transformed}&limit=10"
        data_d1, status_d1 = make_fda_api_call(url_d1, normalized_name)
        if status_d1 == "SUCCESS":
            label, matched_name, data_quality = evaluate_label_candidates(data_d1)
            if label is not None:
                logger.info("'%s': Matched on step D1 (transformed generic_name).", normalized_name)
                return label, extract_clinical_fields_from_label(label), matched_name, data_quality
        if status_d1 not in ("NOT_FOUND", "SUCCESS"):
            had_any_transient_error = True

        url_d2 = f"https://api.fda.gov/drug/label.json?search=openfda.substance_name:{encoded_transformed}&limit=10"
        data_d2, status_d2 = make_fda_api_call(url_d2, normalized_name)
        if status_d2 == "SUCCESS":
            label, matched_name, data_quality = evaluate_label_candidates(data_d2)
            if label is not None:
                logger.info("'%s': Matched on step D2 (transformed substance_name).", normalized_name)
                return label, extract_clinical_fields_from_label(label), matched_name, data_quality
        if status_d2 not in ("NOT_FOUND", "SUCCESS"):
            had_any_transient_error = True

    if had_any_transient_error:
        logger.warning("'%s': All cascade steps failed (some with transient errors).", normalized_name)
    else:
        logger.warning("'%s': All cascade steps returned 404 — genuinely not found.", normalized_name)

    return None, None, None, None


def build_enriched_content_text(
    normalized_generic_name: str,
    matched_openfda_name: Optional[str],
    data_quality: str,
    clinical_fields: dict,
    route_strings: list,
    pharm_class_strings: list,
    known_brand_names_sample: list,
) -> str:
    """
    Build the rich content format — identical to patch2 script's build_enriched_content_text.
    This ensures the updated record is structurally consistent with the other 1,007 records.
    """
    MISSING_LABEL = "Not specified in FDA label"

    header = f"Drug: {normalized_generic_name.upper()} (FDA name: {matched_openfda_name})"

    pharm_line = ""
    if pharm_class_strings:
        clean = [c.replace("[EPC]", "").replace("[MoA]", "").strip() for c in pharm_class_strings]
        pharm_line = f"\n\nTherapeutic Class: {'; '.join(clean)}"

    route_line = ""
    if route_strings:
        route_line = f"\n\nRoutes of Administration: {', '.join(route_strings)}"

    brand_line = ""
    if known_brand_names_sample:
        brand_line = f"\n\nKnown Indian Brand Names (sample): {', '.join(known_brand_names_sample[:20])}"

    dosage_text = clinical_fields.get("dosage_and_administration", "") or MISSING_LABEL
    pregnancy_text = clinical_fields.get("pregnancy_or_breastfeeding", "") or MISSING_LABEL
    pediatric_text = clinical_fields.get("pediatric_use", "") or MISSING_LABEL
    warnings_text = clinical_fields.get("warnings", "") or MISSING_LABEL
    interactions_text = clinical_fields.get("drug_interactions", "") or MISSING_LABEL
    contraindications_text = clinical_fields.get("contraindications", "") or MISSING_LABEL

    clinical_section = (
        f"\n\nDosage and Administration: {dosage_text}"
        f"\n\nPregnancy and Breastfeeding Use: {pregnancy_text}"
        f"\n\nPediatric Use: {pediatric_text}"
        f"\n\nWarnings and Precautions: {warnings_text}"
        f"\n\nDrug Interactions: {interactions_text}"
        f"\n\nContraindications: {contraindications_text}"
    )

    if data_quality == "combination_product":
        disclaimer = (
            f"NOTE: The following clinical data is sourced from a COMBINATION product "
            f"containing this ingredient alongside others (FDA product: {matched_openfda_name}), "
            "not this ingredient alone. Dosage and interaction specifics may not directly "
            "apply to a single-ingredient formulation."
        )
        return f"{disclaimer}\n\n{header}{pharm_line}{route_line}{clinical_section}{brand_line}".strip()
    else:
        return f"{header}{pharm_line}{route_line}{clinical_section}{brand_line}".strip()


def build_identity_only_content_text(normalized_generic_name: str, known_brand_names_sample: list) -> str:
    """
    Build honest identity_only content — used when FDA returns confirmed no data.
    Uses the SAME pattern as the other 577 identity_only records.
    NOT used for transient fetch failures (those get fetch-incomplete text).
    """
    disclaimer = (
        f"FDA clinical monograph data (dosage, pregnancy/pediatric guidance, interactions) "
        f"is not available for {normalized_generic_name.upper()} — it is not currently "
        "approved for marketing in the United States. Please verify dosing against Indian "
        "prescribing references before use."
    )
    brand_line = ""
    if known_brand_names_sample:
        brand_line = f"\n\nKnown Indian Brand Names (sample): {', '.join(known_brand_names_sample[:20])}"
    return f"Drug: {normalized_generic_name.upper()}\n\n{disclaimer}{brand_line}".strip()


def update_ckb_row(
    database_session: Session,
    sku_id: str,
    normalized_generic_name: str,
    new_content_text: str,
    new_embedding_vector: list,
    new_data_quality: str,
) -> bool:
    """
    UPDATE one CKB row — content, embedding, and data_quality.
    Uses a targeted WHERE sku_id = :sku_id so only this record is touched.
    """
    try:
        # Use a simpler UPDATE with JSON building in Python to avoid
        # parameter binding conflicts with PostgreSQL's ::jsonb cast syntax.
        import json
        new_metadata = {
            "generic_name": normalized_generic_name,
            "data_quality": new_data_quality,
            "source": "openfda_generic_reference",
        }
        database_session.execute(
            sa_text(
                "UPDATE clinical_knowledge_base "
                "SET content = :content, "
                "    embedding = :embedding, "
                "    metadata_payload = :metadata_payload "
                "WHERE sku_id = :sku_id"
            ),
            {
                "content": new_content_text,
                "embedding": str(new_embedding_vector),
                "sku_id": sku_id,
                "metadata_payload": json.dumps(new_metadata),
            },
        )
        database_session.commit()
        return True

    except Exception as error:
        database_session.rollback()
        logger.error("Failed to update CKB row for '%s' (sku: %s). Error: %s", normalized_generic_name, sku_id, error)
        return False


def main() -> None:
    script_start = time.time()

    print("=" * 72)
    print("  fix(5.5-f3a): RE-FETCH EMPTY/FAILED OpenFDA RECORDS")
    print("=" * 72)

    generics_to_fix = list(CONFIRMED_BROKEN_SKUS.keys())

    # =========================================================================
    # STEP 1 — Report before-state and confirm only broken records are targeted
    # =========================================================================
    print("\n--- STEP 1: Pre-fix state of confirmed broken records ---")

    db_session = SessionLocal()
    before_lengths = {}
    brand_sample_map = {}

    try:
        for generic_name, sku_id in CONFIRMED_BROKEN_SKUS.items():
            row = db_session.execute(
                sa_text("SELECT length(content) AS len FROM clinical_knowledge_base WHERE sku_id = :sku_id"),
                {"sku_id": sku_id}
            ).fetchone()
            before_lengths[generic_name] = row.len if row else 0
            print(f"  {generic_name:<40s}  sku: {sku_id:<50s}  BEFORE length: {before_lengths[generic_name]:,}")

            # Load brand name sample for content building
            rows = db_session.execute(
                sa_text("SELECT alias_text FROM drug_brand_aliases WHERE sku_id = :sku_id AND alias_type = 'brand_name' ORDER BY alias_text LIMIT 20"),
                {"sku_id": sku_id}
            ).fetchall()
            brand_sample_map[generic_name] = [r[0] for r in rows]

        # Confirm total rows untouched
        total_ckb = db_session.execute(sa_text("SELECT COUNT(*) FROM clinical_knowledge_base")).scalar()
        total_identity = db_session.execute(sa_text(
            "SELECT COUNT(*) FROM clinical_knowledge_base WHERE metadata_payload->>'data_quality' = 'identity_only'"
        )).scalar()
        total_real = db_session.execute(sa_text(
            "SELECT COUNT(*) FROM clinical_knowledge_base WHERE metadata_payload->>'source' = 'openfda_generic_reference' AND metadata_payload->>'data_quality' != 'identity_only'"
        )).scalar()

        print(f"\n  DB counts before fix:")
        print(f"    total CKB rows         : {total_ckb}")
        print(f"    identity_only (577)    : {total_identity}")
        print(f"    real generics (1,008)  : {total_real}")
    finally:
        db_session.close()

    # =========================================================================
    # STEP 2 — Run the full 4-step cascade for each broken generic
    # =========================================================================
    print("\n--- STEP 2: Running 4-step cascade for each broken record ---")

    cascade_results: list[dict] = []

    for generic_name in generics_to_fix:
        logger.info("--- Trying: %s ---", generic_name)
        full_label, clinical_fields, matched_name, data_quality = run_full_cascade_for_generic(generic_name)

        cascade_results.append({
            "normalized_name": generic_name,
            "sku_id": CONFIRMED_BROKEN_SKUS[generic_name],
            "matched": full_label is not None,
            "matched_name": matched_name,
            "data_quality": data_quality,
            "clinical_fields": clinical_fields,
            "full_label": full_label,
        })

    # =========================================================================
    # STEP 3 — Build content texts for each
    # =========================================================================
    print("\n--- STEP 3: Building new content texts ---")

    content_map: dict[str, tuple[str, str]] = {}  # name -> (content, data_quality)

    for result in cascade_results:
        generic_name = result["normalized_name"]
        brands = brand_sample_map.get(generic_name, [])

        if result["matched"]:
            full_label = result["full_label"]
            openfda_block = full_label.get("openfda", {})
            route_strings = openfda_block.get("route", [])
            pharm_class_strings = openfda_block.get("pharm_class_epc", [])

            content = build_enriched_content_text(
                normalized_generic_name=generic_name,
                matched_openfda_name=result["matched_name"],
                data_quality=result["data_quality"],
                clinical_fields=result["clinical_fields"],
                route_strings=route_strings,
                pharm_class_strings=pharm_class_strings,
                known_brand_names_sample=brands,
            )
            new_quality = result["data_quality"]
            logger.info("'%s': Will write ENRICHED content (%d chars).", generic_name, len(content))
        else:
            # FDA returned nothing even after 4-step cascade.
            # Reclassify as identity_only — same honest-disclosure pattern used for the 577.
            content = build_identity_only_content_text(generic_name, brands)
            new_quality = "identity_only"
            logger.info("'%s': Will write IDENTITY_ONLY content (reclassified).", generic_name)

        content_map[generic_name] = (content, new_quality)

    # =========================================================================
    # STEP 4 — Generate embeddings for the new content texts
    # =========================================================================
    print("\n--- STEP 4: Generating new embeddings ---")

    import torch
    from sentence_transformers import SentenceTransformer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("Using device: %s", device)
    model = SentenceTransformer("NeuML/pubmedbert-base-embeddings", device=device)
    logger.info("Model loaded.")

    ordered_texts = [content_map[name][0] for name in generics_to_fix]
    embed_start = time.time()
    embeddings_array = model.encode(ordered_texts, batch_size=16, show_progress_bar=False).tolist()
    embed_seconds = time.time() - embed_start
    logger.info("Generated %d embeddings in %.1fs.", len(embeddings_array), embed_seconds)

    # =========================================================================
    # STEP 5 — Update database rows
    # =========================================================================
    print("\n--- STEP 5: Updating CKB rows in database ---")

    db_session = SessionLocal()
    update_results: list[dict] = []

    try:
        for i, generic_name in enumerate(generics_to_fix):
            sku_id = CONFIRMED_BROKEN_SKUS[generic_name]
            new_content, new_quality = content_map[generic_name]
            new_embedding = embeddings_array[i]
            cascade_result = cascade_results[i]

            success = update_ckb_row(
                database_session=db_session,
                sku_id=sku_id,
                normalized_generic_name=generic_name,
                new_content_text=new_content,
                new_embedding_vector=new_embedding,
                new_data_quality=new_quality,
            )

            final_status = (
                "ENRICHED" if (cascade_result["matched"] and success)
                else "RECLASSIFIED_AS_IDENTITY_ONLY" if (not cascade_result["matched"] and success)
                else "DB_UPDATE_FAILED"
            )

            update_results.append({
                "generic_name": generic_name,
                "sku_id": sku_id,
                "before_len": before_lengths.get(generic_name, 0),
                "new_content_len": len(new_content),
                "cascade_matched": cascade_result["matched"],
                "matched_name": cascade_result.get("matched_name"),
                "final_status": final_status,
                "db_ok": success,
            })

            logger.info(
                "  %s → cascade: %s | db: %s | status: %s | new_len: %d",
                generic_name,
                "MATCHED" if cascade_result["matched"] else "NO_MATCH",
                "OK" if success else "FAILED",
                final_status,
                len(new_content),
            )
    finally:
        db_session.close()

    # =========================================================================
    # STEP 6 — Verify after-state: lengths, row counts
    # =========================================================================
    print("\n--- STEP 6: Post-fix verification ---")

    verify_session = SessionLocal()
    try:
        after_total_ckb = verify_session.execute(sa_text("SELECT COUNT(*) FROM clinical_knowledge_base")).scalar()
        after_identity = verify_session.execute(sa_text(
            "SELECT COUNT(*) FROM clinical_knowledge_base WHERE metadata_payload->>'data_quality' = 'identity_only'"
        )).scalar()
        after_real = verify_session.execute(sa_text(
            "SELECT COUNT(*) FROM clinical_knowledge_base WHERE metadata_payload->>'source' = 'openfda_generic_reference' AND metadata_payload->>'data_quality' != 'identity_only'"
        )).scalar()

        print(f"\n  DB counts after fix:")
        print(f"    total CKB rows         : {after_total_ckb}")
        print(f"    identity_only          : {after_identity}")
        print(f"    real generics          : {after_real}")

        print(f"\n  Before/after lengths for touched records:")
        for r in update_results:
            after_row = verify_session.execute(
                sa_text("SELECT length(content) FROM clinical_knowledge_base WHERE sku_id = :sku_id"),
                {"sku_id": r["sku_id"]}
            ).fetchone()
            after_len = after_row[0] if after_row else 0
            print(f"    {r['generic_name']:<30s}  BEFORE: {r['before_len']:>6,}  AFTER: {after_len:>8,}  status: {r['final_status']}")

    finally:
        verify_session.close()

    # =========================================================================
    # FINAL REPORT
    # =========================================================================
    total_elapsed = time.time() - script_start
    print("\n" + "=" * 72)
    print("  FINAL REPORT")
    print("=" * 72)

    for r in update_results:
        cascade_str = f"MATCHED → {r['matched_name']}" if r["cascade_matched"] else "NO MATCH"
        print(f"  {r['generic_name']:<25}  {cascade_str:<40}  {r['final_status']}")

    enriched = sum(1 for r in update_results if r["final_status"] == "ENRICHED")
    reclassified = sum(1 for r in update_results if r["final_status"] == "RECLASSIFIED_AS_IDENTITY_ONLY")
    failed = sum(1 for r in update_results if r["final_status"] == "DB_UPDATE_FAILED")

    print(f"\n  Successfully enriched with real FDA data : {enriched}")
    print(f"  Reclassified as identity_only (honest)  : {reclassified}")
    print(f"  DB update failures                       : {failed}")
    print(f"  Total records touched                    : {len(update_results)}")
    print(f"  Embedding time: {embed_seconds:.1f}s | Total time: {total_elapsed:.1f}s")
    print("=" * 72)


if __name__ == "__main__":
    main()
