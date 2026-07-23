"""
Step 5.2e-patch-2: Retry 15 Fetch-Failed Generics with Full 4-Step Cascade
============================================================================

Beginner Note — WHY this script exists:
    In 5.2e-patch, 15 generics failed to fetch their clinical data. The patch
    script used a single "reconstructed" query per generic — the exact same
    query that worked during the original 5.2f cascade run. But because we're
    now asking for a DIFFERENT endpoint (the full label rather than just the
    openfda sub-block), some of those reconstructed queries returned 404 even
    though data might exist under a different query variation.

    This script gives each of those 15 generics a second chance by running
    the COMPLETE 4-step cascade exactly as 5.2f did, trying every possible
    query approach in sequence. If a match is found, we extract the full
    clinical fields and update the database row with real data. If a match
    still can't be found, we update the content to say so HONESTLY — using
    "fetch-incomplete" wording that explicitly distinguishes this situation
    from the 577 confirmed-NO_FDA_DATA generics (where we know the drug is
    not FDA-approved) — because "the fetch failed" and "confirmed unavailable"
    are two very different things clinically.

    The 15 generics being retried:
        paclitaxel, chloroquine, isoniazid, sulfamethoxazole, erythromycin,
        nitrofurantoin, halobetasol, sodium hyaluronate, pancreatin,
        sodium bicarbonate, venlafaxine, lisinopril, sertaconazole,
        trifluoperazine, abemaciclib

HOW TO RUN (inside Docker):
    docker compose exec api python scripts/retry_failed_fetches_52e_patch2.py
"""

import json
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

# ---------------------------------------------------------------------------
# LOGGING SETUP
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# THE 15 GENERICS TO RETRY
# These are the exact names that were written as FETCH_FAILED or 404 in the
# openfda_full_clinical_fields.jsonl output file from 5.2e-patch.
# ---------------------------------------------------------------------------
GENERICS_TO_RETRY: list[str] = [
    "paclitaxel",
    "chloroquine",
    "isoniazid",
    "sulfamethoxazole",
    "erythromycin",
    "nitrofurantoin",
    "halobetasol",
    "sodium hyaluronate",
    "pancreatin",
    "sodium bicarbonate",
    "venlafaxine",
    "lisinopril",
    "sertaconazole",
    "trifluoperazine",
    "abemaciclib",
]

# The SKU prefix used when these rows were created in 5.2e.
GENERIC_SKU_PREFIX = "GENERIC_REF_"

# Delay between each FDA API request. 350ms keeps us well within rate limits.
REQUEST_DELAY_SECONDS = 0.35

# ---------------------------------------------------------------------------
# ALIAS DICTIONARY AND SPELLING TRANSFORM — identical to 5.2f and 5.2e-patch.
# These MUST NOT be redefined differently, or our cascade logic will diverge
# from the original and produce inconsistent results.
# ---------------------------------------------------------------------------

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
    """
    WHY THIS EXISTS:
        Some Indian drug names use British spellings not recognized by the FDA.
        For example, "sulphamethoxazole" (British) → "sulfamethoxazole" (US FDA).
        This transform converts those spellings so step_d of the cascade can
        find a match where the direct name lookup failed.

        This MUST be the identical function from 5.2f and 5.2e-patch — any
        deviation would cause different results for the same drug names.
    """
    if not isinstance(raw_name, str):
        return ""
    name = raw_name.replace("sulph", "sulf")
    name = name.replace("oestr", "estr")
    name = name.replace("haem", "hem")
    name = name.replace("amoxy", "amoxi")
    return name


# ---------------------------------------------------------------------------
# FDA API CALL — single query with retry and rate-limit handling
# ---------------------------------------------------------------------------

def make_fda_api_call(
    query_url: str,
    generic_name_for_logging: str,
    max_retries: int = 3,
) -> tuple[Optional[dict], str]:
    """
    WHY THIS EXISTS:
        The FDA API occasionally returns transient errors (timeouts, 500s, 429s).
        Rather than giving up immediately on the first error, we retry with
        exponential backoff. This gives each query a fair chance even if the
        network has a brief hiccup.

        Returns the parsed JSON response plus a status string. The caller
        decides whether a result is useful, not this function.

    Returns:
        Tuple of (response_data, status_string).
        status_string is one of: "SUCCESS", "NOT_FOUND", "RATE_LIMITED",
        "TIMEOUT", "CONNECTION_ERROR", "MAX_RETRIES", or "HTTP_NNN".
    """
    backoff_seconds = 1.0

    for attempt in range(max_retries + 1):
        # Always pause between requests to be a good API citizen.
        time.sleep(REQUEST_DELAY_SECONDS)

        try:
            response = requests.get(query_url, timeout=10)

            if response.status_code == 200:
                return response.json(), "SUCCESS"

            elif response.status_code == 404:
                # 404 means genuinely no results for this query — not a transient error.
                # Don't retry, move on to the next cascade step.
                return None, "NOT_FOUND"

            elif response.status_code == 429:
                # Rate limited. Back off significantly longer than usual.
                logger.warning(
                    "'%s': Rate limited (429). Sleeping %.0fs before retry.",
                    generic_name_for_logging, backoff_seconds + 5.0,
                )
                time.sleep(backoff_seconds + 5.0)
                backoff_seconds *= 2

            elif response.status_code >= 500:
                logger.warning(
                    "'%s': Server error HTTP %d (attempt %d). Retrying in %.0fs.",
                    generic_name_for_logging, response.status_code, attempt + 1, backoff_seconds,
                )
                time.sleep(backoff_seconds)
                backoff_seconds *= 2

            else:
                # Any other unexpected status code (4xx) — not worth retrying.
                return None, f"HTTP_{response.status_code}"

        except requests.exceptions.Timeout:
            logger.warning(
                "'%s': Request timed out (attempt %d). Retrying in %.0fs.",
                generic_name_for_logging, attempt + 1, backoff_seconds,
            )
            time.sleep(backoff_seconds)
            backoff_seconds *= 2

        except requests.exceptions.ConnectionError:
            logger.warning(
                "'%s': Connection error (attempt %d). Retrying in %.0fs.",
                generic_name_for_logging, attempt + 1, backoff_seconds,
            )
            time.sleep(backoff_seconds)
            backoff_seconds *= 2

    return None, "MAX_RETRIES"


# ---------------------------------------------------------------------------
# CANDIDATE EVALUATION — picks the best label from a result set
# ---------------------------------------------------------------------------

def evaluate_label_candidates(
    api_response: dict,
) -> tuple[Optional[dict], Optional[str], Optional[str]]:
    """
    WHY THIS EXISTS:
        An OpenFDA query can return up to 10 label records. We need to pick
        the most appropriate one for our purpose. The rules from 5.2f:
          1. If any result has exactly 1 generic_name in its openfda block,
             prefer that — it's a pure single-ingredient product.
          2. Otherwise, take the first result but label it "combination_product".

        This function returns the chosen FULL label record (not just the openfda
        sub-block) so the caller can extract clinical fields from it directly.

    Returns:
        Tuple of (full_label_dict, matched_openfda_name, data_quality).
        All three are None if the response had no usable results.
    """
    results = api_response.get("results", [])
    if not results:
        return None, None, None

    # Try to find a single-ingredient label first.
    for result in results:
        openfda = result.get("openfda", {})
        generic_name_list = openfda.get("generic_name", [])
        if len(generic_name_list) == 1:
            # This label belongs to a pure single-ingredient product — ideal.
            matched_name = generic_name_list[0]
            return result, matched_name, "single_ingredient"

    # No single-ingredient label found — take the first result as a combo.
    first_result = results[0]
    openfda = first_result.get("openfda", {})
    generic_names = openfda.get("generic_name", openfda.get("substance_name", []))
    matched_name = generic_names[0] if generic_names else None
    return first_result, matched_name, "combination_product"


# ---------------------------------------------------------------------------
# CLINICAL FIELD EXTRACTION — pulls text from a full label record
# ---------------------------------------------------------------------------

def extract_clinical_fields_from_label(full_label: dict) -> dict:
    """
    WHY THIS EXISTS:
        The clinical information we care about (dosage, pregnancy, warnings, etc.)
        lives as top-level keys in the label record. Different generations of
        FDA labels use slightly different key names (e.g. "warnings" vs
        "warnings_and_cautions"). This function tries all known variants and
        returns clean, collapsed text for each field.

        An empty string is returned for any field that is genuinely absent from
        this specific label — we never fabricate content.
    """

    def extract_text(*field_names: str) -> str:
        """
        Try each field name in the given label dict, return the first found.
        Joins list entries and collapses whitespace for clean text.
        """
        for field_name in field_names:
            raw_value = full_label.get(field_name)
            if raw_value:
                if isinstance(raw_value, list):
                    combined = " ".join(str(v) for v in raw_value)
                else:
                    combined = str(raw_value)
                # Collapse multiple spaces left behind by HTML rendering artifacts.
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


# ---------------------------------------------------------------------------
# FULL 4-STEP CASCADE — same logic as 5.2f, applied to one generic
# ---------------------------------------------------------------------------

def run_full_cascade_for_generic(
    normalized_name: str,
) -> tuple[Optional[dict], Optional[dict], Optional[str], Optional[str]]:
    """
    WHY THIS EXISTS:
        In 5.2e-patch, we only tried the single query step that originally
        worked for each generic. But those were querying a different endpoint
        (openfda sub-block only, via the cascade's inner evaluate_candidates).
        Here, we run the complete 4-step cascade against the full label endpoint,
        which may succeed at a different step than the original 5.2f run.

        The cascade logic is intentionally identical to 5.2f so results are
        consistent and reproducible.

    Returns:
        A tuple of (full_label_dict, clinical_fields_dict, matched_name, data_quality).
        All four are None if every step of the cascade failed.
    """
    # Track whether ANY step got a transient error (vs genuine "not found").
    # This helps us distinguish "unknown" from "confirmed absent".
    had_any_transient_error = False

    # ---- Step A: Direct generic name search --------------------------------
    # The simplest attempt — search for the exact normalized name in generic_name.
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

    # ---- Step B: Known alias lookup ----------------------------------------
    # Some Indian names map to different FDA names (e.g. paracetamol → acetaminophen).
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

    # ---- Step C: Substance name search -------------------------------------
    # Some drugs are indexed under substance_name rather than generic_name.
    # We use the alias if available, otherwise the raw normalized name.
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

    # ---- Step D: British→American spelling transform -----------------------
    # "Sulphamethoxazole" (British) becomes "sulfamethoxazole" (FDA spelling).
    # Try the transformed name against both generic_name and substance_name.
    transformed_name = transform_spelling(normalized_name)
    if transformed_name != normalized_name:
        encoded_transformed = urllib.parse.quote(f'"{transformed_name}"')

        # Step D1: transformed generic_name search
        url_d1 = f"https://api.fda.gov/drug/label.json?search=openfda.generic_name:{encoded_transformed}&limit=10"
        data_d1, status_d1 = make_fda_api_call(url_d1, normalized_name)

        if status_d1 == "SUCCESS":
            label, matched_name, data_quality = evaluate_label_candidates(data_d1)
            if label is not None:
                logger.info("'%s': Matched on step D (transformed generic_name: '%s').", normalized_name, transformed_name)
                return label, extract_clinical_fields_from_label(label), matched_name, data_quality

        if status_d1 not in ("NOT_FOUND", "SUCCESS"):
            had_any_transient_error = True

        # Step D2: transformed substance_name search
        url_d2 = f"https://api.fda.gov/drug/label.json?search=openfda.substance_name:{encoded_transformed}&limit=10"
        data_d2, status_d2 = make_fda_api_call(url_d2, normalized_name)

        if status_d2 == "SUCCESS":
            label, matched_name, data_quality = evaluate_label_candidates(data_d2)
            if label is not None:
                logger.info("'%s': Matched on step D (transformed substance_name: '%s').", normalized_name, transformed_name)
                return label, extract_clinical_fields_from_label(label), matched_name, data_quality

        if status_d2 not in ("NOT_FOUND", "SUCCESS"):
            had_any_transient_error = True

    # All 4 steps exhausted — this generic has no usable FDA label data.
    if had_any_transient_error:
        logger.warning("'%s': All cascade steps failed (some with transient errors).", normalized_name)
    else:
        logger.warning("'%s': All cascade steps returned 404 — genuinely not found in FDA labels.", normalized_name)

    return None, None, None, None


# ---------------------------------------------------------------------------
# CONTENT TEXT BUILDERS
# ---------------------------------------------------------------------------

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
    WHY THIS EXISTS:
        When the cascade succeeds, we build the same rich content format used
        in 5.2e-patch — with all 6 clinical sections labeled. This keeps the
        content format consistent across all updated rows so the embedding
        model produces comparable vectors regardless of which script wrote them.
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


def build_fetch_incomplete_content_text(
    normalized_generic_name: str,
    known_brand_names_sample: list,
) -> str:
    """
    WHY THIS EXISTS:
        When we CANNOT retrieve FDA data for a generic after the full cascade
        retry, we must be honest about WHY. There are two very different reasons
        a CKB row might lack clinical data:

          1. "NO_FDA_DATA" (577 generics) — the drug is confirmed NOT approved
             for marketing in the US. We genuinely have no data, and we know why.

          2. "fetch-incomplete" (this function) — our API calls failed technically.
             We don't know whether the drug has FDA data or not. The failure
             might be a temporary API outage, a search index gap, or the drug
             genuinely having no label. We cannot confirm which.

        Conflating these two would be dishonest to a pharmacist relying on this
        system. This function generates "fetch-incomplete" wording that clearly
        flags the uncertainty without falsely implying confirmed unavailability.
    """
    disclaimer = (
        f"FDA clinical monograph data could not be retrieved for "
        f"{normalized_generic_name.upper()} after multiple fetch attempts "
        "(technical fetch issue — this does not confirm the drug is unavailable "
        "in FDA records, only that our retrieval failed). "
        "Please verify dosing against Indian prescribing references before use."
    )

    brand_line = ""
    if known_brand_names_sample:
        brand_line = f"\n\nKnown Indian Brand Names (sample): {', '.join(known_brand_names_sample[:20])}"

    return f"Drug: {normalized_generic_name.upper()}\n\n{disclaimer}{brand_line}".strip()


# ---------------------------------------------------------------------------
# DATABASE UPDATE — atomic per generic
# ---------------------------------------------------------------------------

def update_ckb_row(
    database_session: Session,
    normalized_generic_name: str,
    new_content_text: str,
    new_embedding_vector: list[float],
) -> bool:
    """
    WHY THIS EXISTS:
        We UPDATE existing rows in clinical_knowledge_base — never insert,
        never delete. Each update is its own commit so a failure on one generic
        doesn't roll back any other generic's already-committed update.

        We do NOT touch metadata_payload.data_quality in this script.
        Whether the original 5.2e set it to "single_ingredient" or
        "combination_product", that label came from the cascade match and
        remains correct. We only change content and embedding.

    Returns:
        True if the update committed successfully, False if it failed.
    """
    generic_sku_id = f"{GENERIC_SKU_PREFIX}{normalized_generic_name.upper()}"

    try:
        database_session.execute(
            sa_text(
                "UPDATE clinical_knowledge_base "
                "SET content = :content, embedding = :embedding "
                "WHERE sku_id = :sku_id"
            ),
            {
                "content": new_content_text,
                "embedding": str(new_embedding_vector),
                "sku_id": generic_sku_id,
            }
        )
        database_session.commit()
        return True

    except Exception as error:
        database_session.rollback()
        logger.error(
            "Failed to update CKB row for '%s' (sku: %s). Error: %s",
            normalized_generic_name, generic_sku_id, error,
        )
        return False


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main() -> None:
    """
    WHY THIS EXISTS:
        This function orchestrates the entire retry pipeline. Reading it from
        top to bottom gives the complete picture of what happens and why.
    """
    script_start = time.time()

    print("=" * 72)
    print("  5.2e-PATCH-2: RETRY 15 FETCH-FAILED GENERICS")
    print("=" * 72)

    # ======================================================================
    # PHASE 1: Load brand name samples from drug_brand_aliases
    # (needed for content text construction if cascade succeeds or fails)
    # ======================================================================
    logger.info("Phase 1: Loading brand name samples for the 15 generics...")

    db_session = SessionLocal()
    brand_sample_map: dict[str, list[str]] = {}
    try:
        for generic_name in GENERICS_TO_RETRY:
            sku_id = f"{GENERIC_SKU_PREFIX}{generic_name.upper()}"
            rows = db_session.execute(
                sa_text(
                    "SELECT alias_text FROM drug_brand_aliases "
                    "WHERE sku_id = :sku_id AND alias_type = 'brand_name' "
                    "ORDER BY alias_text LIMIT 20"
                ),
                {"sku_id": sku_id}
            ).fetchall()
            brand_sample_map[generic_name] = [row[0] for row in rows]
    finally:
        db_session.close()

    logger.info("Brand samples loaded for %d generics.", len(brand_sample_map))

    # ======================================================================
    # PHASE 2: Run the full 4-step cascade for each of the 15 generics
    # ======================================================================
    logger.info("Phase 2: Running full cascade for 15 generics...")

    # We collect results here before touching the DB or the model, so that
    # a cascade failure mid-loop doesn't leave us with a half-embedded set.
    cascade_results: list[dict] = []

    for generic_name in GENERICS_TO_RETRY:
        logger.info("--- Trying: %s ---", generic_name)
        full_label, clinical_fields, matched_name, data_quality = run_full_cascade_for_generic(generic_name)

        cascade_results.append({
            "normalized_name": generic_name,
            "matched": full_label is not None,
            "matched_name": matched_name,
            "data_quality": data_quality,
            "clinical_fields": clinical_fields,
            "full_label": full_label,
        })

    matched_count = sum(1 for r in cascade_results if r["matched"])
    still_failing_count = len(cascade_results) - matched_count
    logger.info(
        "Cascade complete. %d recovered, %d still failing after full retry.",
        matched_count, still_failing_count,
    )

    # ======================================================================
    # PHASE 3: Build all new content texts
    # ======================================================================
    logger.info("Phase 3: Building content texts for all 15 generics...")

    content_map: dict[str, str] = {}

    for result in cascade_results:
        generic_name = result["normalized_name"]
        brands = brand_sample_map.get(generic_name, [])

        if result["matched"]:
            # We got real clinical data — build the rich format.
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
        else:
            # Still no data — write the honest "fetch-incomplete" content.
            content = build_fetch_incomplete_content_text(
                normalized_generic_name=generic_name,
                known_brand_names_sample=brands,
            )

        content_map[generic_name] = content

    # ======================================================================
    # PHASE 4: Batch-generate embeddings for all 15 content texts
    # ======================================================================
    logger.info("Phase 4: Generating embeddings for 15 content texts...")

    import torch
    from sentence_transformers import SentenceTransformer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("Using device: %s", device)

    model = SentenceTransformer("NeuML/pubmedbert-base-embeddings", device=device)
    logger.info("Model ready.")

    # Build the list in the same order as GENERICS_TO_RETRY for alignment.
    ordered_texts = [content_map[name] for name in GENERICS_TO_RETRY]
    embed_start = time.time()
    embeddings_array = model.encode(ordered_texts, batch_size=16, show_progress_bar=False).tolist()
    embed_seconds = time.time() - embed_start

    logger.info("Generated %d embeddings in %.1fs.", len(embeddings_array), embed_seconds)

    # ======================================================================
    # PHASE 5: Update each CKB row — one atomic transaction per generic
    # ======================================================================
    logger.info("Phase 5: Updating clinical_knowledge_base rows...")

    db_session = SessionLocal()
    update_results: list[dict] = []

    try:
        for i, generic_name in enumerate(GENERICS_TO_RETRY):
            new_content = content_map[generic_name]
            new_embedding = embeddings_array[i]
            cascade_result = cascade_results[i]

            success = update_ckb_row(
                database_session=db_session,
                normalized_generic_name=generic_name,
                new_content_text=new_content,
                new_embedding_vector=new_embedding,
            )

            update_results.append({
                "generic_name": generic_name,
                "cascade_matched": cascade_result["matched"],
                "matched_name": cascade_result["matched_name"],
                "data_quality": cascade_result["data_quality"],
                "db_update_succeeded": success,
                "final_status": (
                    "ENRICHED" if (cascade_result["matched"] and success)
                    else "FETCH_INCOMPLETE_TAGGED" if (not cascade_result["matched"] and success)
                    else "DB_UPDATE_FAILED"
                ),
            })

            logger.info(
                "  %s → cascade: %s | db update: %s | final: %s",
                generic_name,
                "MATCHED" if cascade_result["matched"] else "NO_MATCH",
                "OK" if success else "FAILED",
                update_results[-1]["final_status"],
            )
    finally:
        db_session.close()

    # ======================================================================
    # PHASE 6: Verify table row counts are unchanged
    # ======================================================================
    verify_session = SessionLocal()
    try:
        meds_count = verify_session.execute(sa_text("SELECT COUNT(*) FROM medications")).scalar()
        ckb_count = verify_session.execute(sa_text("SELECT COUNT(*) FROM clinical_knowledge_base")).scalar()
        aliases_count = verify_session.execute(sa_text("SELECT COUNT(*) FROM drug_brand_aliases")).scalar()
    finally:
        verify_session.close()

    total_elapsed = time.time() - script_start

    # ======================================================================
    # FINAL REPORT
    # ======================================================================
    print("\n" + "=" * 72)
    print("  RETRY COMPLETE — 5.2e-PATCH-2 REPORT")
    print("=" * 72)

    print("\nResults per generic:")
    print(f"  {'Generic':<25} {'Cascade Match?':<16} {'Step / FDA Name':<35} {'Final Status'}")
    print("  " + "-" * 100)
    for r in update_results:
        cascade_str = f"MATCHED → {r['matched_name']}" if r["cascade_matched"] else "NO MATCH"
        print(f"  {r['generic_name']:<25} {'YES' if r['cascade_matched'] else 'NO':<16} {cascade_str:<35} {r['final_status']}")

    recovered = sum(1 for r in update_results if r["final_status"] == "ENRICHED")
    tagged_incomplete = sum(1 for r in update_results if r["final_status"] == "FETCH_INCOMPLETE_TAGGED")
    db_failed = sum(1 for r in update_results if r["final_status"] == "DB_UPDATE_FAILED")

    print(f"\nFinal tally:")
    print(f"  Successfully recovered (now have real clinical data): {recovered} / 15")
    print(f"  Still failing, tagged as fetch-incomplete:            {tagged_incomplete} / 15")
    print(f"  DB update failures (rare/unexpected):                 {db_failed} / 15")

    print(f"\nTable counts (must not have changed):")
    print(f"  medications:             1614 -> {meds_count}")
    print(f"  clinical_knowledge_base: 1596 -> {ckb_count}")
    print(f"  drug_brand_aliases:   251113 -> {aliases_count}")

    print(f"\nTiming:")
    print(f"  Embedding time:    {embed_seconds:.1f}s")
    print(f"  Total script time: {total_elapsed:.1f}s")
    print("=" * 72)


if __name__ == "__main__":
    main()
