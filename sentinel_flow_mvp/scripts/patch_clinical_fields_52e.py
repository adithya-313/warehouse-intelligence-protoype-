"""
Step 5.2e-patch: Fetch Missing Clinical Fields and Update Existing Records
==========================================================================

Beginner Note — WHY this script exists:
    In step 5.2e, we ingested 1,585 generics into clinical_knowledge_base.
    However, the content stored for the 1,008 MATCHED generics only included
    identity metadata (FDA name, pharmacological class, route, brand aliases).

    The real clinical details — dosage instructions, pregnancy warnings,
    pediatric guidance, drug interactions, contraindications — live as
    SEPARATE top-level keys in the FDA label response object. The original
    5.2f batch fetcher only ever saved the nested `openfda` sub-block, missing
    these clinical keys entirely.

    This script fixes that gap by:
      1. Reading the existing openfda_full_results_corrected.jsonl to know
         exactly WHICH query worked for each MATCHED generic (so we can
         re-hit OpenFDA with one targeted call instead of all 4 cascade steps).
      2. Fetching the FULL label response for each MATCHED generic.
      3. Extracting the clinical text fields (dosage, pregnancy, pediatric,
         warnings, interactions, contraindications).
      4. Rebuilding a richer content text that now includes real clinical data.
      5. Re-embedding that new text and UPDATEing the existing
         clinical_knowledge_base row in place.

    We do NOT touch medications or drug_brand_aliases — only clinical_knowledge_base.content
    and clinical_knowledge_base.embedding are changed.

HOW TO RUN (inside Docker):
    docker compose exec api python scripts/patch_clinical_fields_52e.py

RESUMABILITY:
    Results are written line-by-line to data/staging/openfda_full_clinical_fields.jsonl.
    If this script is interrupted, re-running it skips generics already saved to that file.
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
# FILE PATHS
# ---------------------------------------------------------------------------
OPENFDA_EXISTING_JSONL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "staging", "openfda_full_results_corrected.jsonl",
)

# This is the NEW output file for the clinical fields fetched in this patch step.
CLINICAL_FIELDS_JSONL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "staging", "openfda_full_clinical_fields.jsonl",
)


# ---------------------------------------------------------------------------
# CONSTANTS — reuse EXACTLY the same alias dictionary and spelling transform
# from 5.2f so that our query reconstruction logic matches what actually worked.
# ---------------------------------------------------------------------------

# These are the known Indian/British names that map to different US/FDA names.
# This dict MUST be identical to the one used in 5.2f — if they differ, our
# query reconstruction for step_b generics will hit the wrong FDA record.
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

# The generic SKU prefix we used in 5.2e.
GENERIC_SKU_PREFIX = "GENERIC_REF_"

# Rate limiting: sleep between each API request to stay well within FDA's
# undocumented rate limit (roughly 1000 req/minute with an API key, much less
# without one). 350ms per request keeps us safe.
REQUEST_DELAY_SECONDS = 0.35


# ---------------------------------------------------------------------------
# ALIAS TRANSFORM FUNCTION — identical to 5.2f, do not change
# ---------------------------------------------------------------------------

def transform_spelling(raw_name: str) -> str:
    """
    WHY THIS EXISTS:
        Several Indian drug names use British spellings that don't match the
        FDA's American spelling. For example, "amoxycillin" (Indian) needs to
        become "amoxicillin" (FDA). We apply a small set of known rules to
        convert Indian/British spelling variants to their US equivalents.

        This function MUST be the exact same one used in 5.2f — otherwise
        generics that matched via step_d will fail to reconstruct the same query.
    """
    if not isinstance(raw_name, str):
        return ""
    name = raw_name.replace("sulph", "sulf")
    name = name.replace("oestr", "estr")
    name = name.replace("haem", "hem")
    name = name.replace("amoxy", "amoxi")
    return name


# ---------------------------------------------------------------------------
# STEP 1 — Reconstruct the exact query for each MATCHED generic
# ---------------------------------------------------------------------------

def reconstruct_query_for_generic(
    normalized_name: str,
    query_step: str,
) -> Optional[tuple[str, str]]:
    """
    WHY THIS EXISTS:
        In step 5.2f, each generic went through a 4-step cascade to find its
        FDA record. Some matched on the first try (step "a"), some required an
        alias lookup (step "b"), some required substance_name search (step "c"),
        and some required a spelling transform (step "d").

        The query_step_that_matched field tells us which approach worked.
        We reconstruct that exact same query here so we can fetch the FULL
        label (including clinical fields) with ONE targeted API call instead
        of blindly re-running all four steps.

    Args:
        normalized_name: The normalized generic name (e.g. "amoxycillin").
        query_step: The step that succeeded ("a", "b", "c", or "d").

    Returns:
        A tuple of (url_string, field_searched) where url_string is the full
        OpenFDA API URL to call, and field_searched is the openfda field used
        (for logging clarity). Returns None if we can't reconstruct the query.
    """
    # Step "a": matched directly on openfda.generic_name using the normalized name
    if query_step == "a":
        encoded_term = urllib.parse.quote(f'"{normalized_name}"')
        url = f"https://api.fda.gov/drug/label.json?search=openfda.generic_name:{encoded_term}&limit=10"
        return url, "openfda.generic_name"

    # Step "b": matched on openfda.generic_name using the US alias
    elif query_step == "b":
        us_alias = KNOWN_ALIASES.get(normalized_name)
        if not us_alias:
            logger.warning(
                "Step_b generic '%s' but no alias found in KNOWN_ALIASES. Skipping.",
                normalized_name,
            )
            return None
        encoded_term = urllib.parse.quote(f'"{us_alias}"')
        url = f"https://api.fda.gov/drug/label.json?search=openfda.generic_name:{encoded_term}&limit=10"
        return url, "openfda.generic_name (alias)"

    # Step "c": matched on openfda.substance_name (using alias if available, else raw name)
    elif query_step == "c":
        search_term = KNOWN_ALIASES.get(normalized_name, normalized_name)
        encoded_term = urllib.parse.quote(f'"{search_term}"')
        url = f"https://api.fda.gov/drug/label.json?search=openfda.substance_name:{encoded_term}&limit=10"
        return url, "openfda.substance_name"

    # Step "d": matched after applying the British->American spelling transform
    elif query_step == "d":
        transformed = transform_spelling(normalized_name)
        encoded_term = urllib.parse.quote(f'"{transformed}"')
        # In 5.2f, step_d tried generic_name first, then substance_name.
        # We default to generic_name here since that's the primary search.
        url = f"https://api.fda.gov/drug/label.json?search=openfda.generic_name:{encoded_term}&limit=10"
        return url, "openfda.generic_name (transformed spelling)"

    else:
        logger.warning("Unknown query step '%s' for generic '%s'. Skipping.", query_step, normalized_name)
        return None


# ---------------------------------------------------------------------------
# STEP 2 — Fetch the full label and extract clinical text fields
# ---------------------------------------------------------------------------

def fetch_full_clinical_label(
    api_url: str,
    normalized_name: str,
    original_data_quality: str,
    max_retries: int = 3,
) -> Optional[dict]:
    """
    WHY THIS EXISTS:
        The OpenFDA API can fail temporarily (rate limits, timeouts, server errors).
        We need to retry with increasing backoff so that a transient failure
        doesn't permanently exclude a generic from getting clinical data.

        We also need to pick the RIGHT result from the up-to-10 returned labels:
        for single_ingredient generics, we prefer the label whose generic_name
        array has only 1 entry (pure single-ingredient product). For combo
        generics, we take the first result since we already know they're combos.

    Args:
        api_url: The full OpenFDA URL to fetch.
        normalized_name: Used for logging only.
        original_data_quality: "single_ingredient" or "combination_product".
            Guides which label we pick from the results.
        max_retries: How many times to retry on transient failure.

    Returns:
        A dict with extracted clinical fields, or None if the fetch ultimately failed.
    """
    backoff_seconds = 1.0

    for attempt in range(max_retries + 1):
        # Rate limiting delay — always sleep before hitting the API to be a
        # good citizen and avoid 429 errors.
        time.sleep(REQUEST_DELAY_SECONDS)

        try:
            response = requests.get(api_url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                if not results:
                    logger.warning("'%s': 200 OK but no results. Marking as empty.", normalized_name)
                    return None

                # Pick the best label from the results. For single-ingredient generics,
                # we prefer a label whose generic_name array has exactly 1 entry —
                # that signals a pure single-ingredient product vs a combo pack.
                chosen_label = None
                if original_data_quality == "single_ingredient":
                    for result in results:
                        openfda = result.get("openfda", {})
                        if len(openfda.get("generic_name", [])) == 1:
                            chosen_label = result
                            break
                    # If no single-ingredient label found, fall back to first result.
                    if chosen_label is None:
                        chosen_label = results[0]
                else:
                    # For combo products, just take the first result.
                    chosen_label = results[0]

                # Extract every clinical field we care about. OpenFDA stores
                # these as arrays of strings — we join them with spaces since
                # a single label section is sometimes split across multiple
                # array entries (e.g. table rows separated).
                def extract_field(label: dict, *field_names: str) -> str:
                    """Try each field name in order, return the first one found."""
                    for field_name in field_names:
                        raw_value = label.get(field_name)
                        if raw_value:
                            # Join array entries and collapse whitespace.
                            if isinstance(raw_value, list):
                                combined = " ".join(str(v) for v in raw_value)
                            else:
                                combined = str(raw_value)
                            # Collapse excessive whitespace left by HTML stripping.
                            return re.sub(r'\s+', ' ', combined).strip()
                    return ""

                # Extract all clinical fields. We check multiple key variants
                # because OpenFDA uses different names across label generations:
                # older labels say "warnings", newer say "warnings_and_cautions".
                clinical_data = {
                    "normalized_generic_name": normalized_name,
                    "dosage_and_administration": extract_field(
                        chosen_label, "dosage_and_administration"
                    ),
                    "pregnancy_or_breastfeeding": extract_field(
                        chosen_label, "pregnancy", "pregnancy_or_breast_feeding"
                    ),
                    "pediatric_use": extract_field(
                        chosen_label, "pediatric_use"
                    ),
                    "warnings": extract_field(
                        chosen_label, "warnings_and_cautions", "warnings",
                        "boxed_warning"
                    ),
                    "drug_interactions": extract_field(
                        chosen_label, "drug_interactions"
                    ),
                    "contraindications": extract_field(
                        chosen_label, "contraindications"
                    ),
                }

                return clinical_data

            elif response.status_code == 404:
                # The query found nothing — drug genuinely not in FDA database
                # under this query. This shouldn't happen for MATCHED generics,
                # but we handle it gracefully.
                logger.warning("'%s': 404 Not Found on full-label fetch.", normalized_name)
                return None

            elif response.status_code == 429:
                # We hit the rate limit. Back off longer than usual.
                logger.warning("'%s': 429 Rate limited. Sleeping %ds before retry.", normalized_name, backoff_seconds + 3)
                time.sleep(backoff_seconds + 3.0)
                backoff_seconds *= 2

            elif response.status_code >= 500:
                # Server-side error. Retry with exponential backoff.
                logger.warning("'%s': HTTP %d server error. Retrying in %ds.", normalized_name, response.status_code, backoff_seconds)
                time.sleep(backoff_seconds)
                backoff_seconds *= 2

            else:
                logger.warning("'%s': Unexpected HTTP %d. Skipping.", normalized_name, response.status_code)
                return None

        except requests.exceptions.Timeout:
            logger.warning("'%s': Request timed out (attempt %d). Retrying in %ds.", normalized_name, attempt + 1, backoff_seconds)
            time.sleep(backoff_seconds)
            backoff_seconds *= 2

        except requests.exceptions.ConnectionError:
            logger.warning("'%s': Connection error (attempt %d). Retrying in %ds.", normalized_name, attempt + 1, backoff_seconds)
            time.sleep(backoff_seconds)
            backoff_seconds *= 2

    # All retries exhausted.
    logger.error("'%s': All %d fetch attempts failed. This generic will keep its old content.", normalized_name, max_retries + 1)
    return None


# ---------------------------------------------------------------------------
# STEP 3 — Build the NEW (richer) content text using real clinical fields
# ---------------------------------------------------------------------------

def build_enriched_content_text(
    normalized_generic_name: str,
    matched_openfda_name: Optional[str],
    data_quality: str,
    clinical_fields: dict,
    route_strings: list,
    pharm_class_strings: list,
    moa_strings: list,
    known_brand_names_sample: list,
) -> str:
    """
    WHY THIS EXISTS:
        The 5.2e content text was sparse — it only had identity info and brand
        names. Now that we have actual clinical text (dosage instructions, pregnancy
        warnings, etc.), we rebuild the content to include all of it in a clean,
        labeled format.

        The embedding model (PubMedBERT) needs well-structured text to produce
        good semantic vectors. A pharmacist asking "is cefixime safe in pregnancy?"
        should now semantically match the "Pregnancy Use" section of our content.

        We keep the same combination_product disclaimer from 5.2e where relevant.
    """
    MISSING_LABEL = "Not specified in FDA label"

    # The drug identity header — names the drug clearly at the start of the
    # content so the embedding model has strong context for what follows.
    header_line = f"Drug: {normalized_generic_name.upper()}"
    if matched_openfda_name:
        header_line += f" (FDA name: {matched_openfda_name})"

    # Pharmacological class from the openfda sub-block (already in our existing
    # metadata from 5.2e — we reconstruct it from the raw_block if available,
    # but we won't call the API again for it since we have enough from the label).
    pharm_line = ""
    if pharm_class_strings:
        clean_classes = [c.replace("[EPC]", "").replace("[MoA]", "").strip() for c in pharm_class_strings]
        pharm_line = f"\n\nTherapeutic Class: {'; '.join(clean_classes)}"

    moa_line = ""
    if moa_strings:
        clean_moa = [c.replace("[MoA]", "").strip() for c in moa_strings]
        moa_line = f"\n\nMechanism of Action: {'; '.join(clean_moa)}"

    route_line = ""
    if route_strings:
        route_line = f"\n\nRoutes of Administration: {', '.join(route_strings)}"

    # Extract the actual clinical field text (or the MISSING_LABEL placeholder
    # if a field is genuinely absent in the FDA label).
    dosage_text = clinical_fields.get("dosage_and_administration", "") or MISSING_LABEL
    pregnancy_text = clinical_fields.get("pregnancy_or_breastfeeding", "") or MISSING_LABEL
    pediatric_text = clinical_fields.get("pediatric_use", "") or MISSING_LABEL
    warnings_text = clinical_fields.get("warnings", "") or MISSING_LABEL
    interactions_text = clinical_fields.get("drug_interactions", "") or MISSING_LABEL
    contraindications_text = clinical_fields.get("contraindications", "") or MISSING_LABEL

    # Brand name section — cap at 20 to avoid the embedding being dominated
    # by a long list of brand names at the expense of the clinical content.
    brand_line = ""
    if known_brand_names_sample:
        brand_line = f"\n\nKnown Indian Brand Names (sample): {', '.join(known_brand_names_sample[:20])}"

    # Clinical sections — these are the NEW additions that were missing before.
    clinical_section = (
        f"\n\nDosage and Administration: {dosage_text}"
        f"\n\nPregnancy and Breastfeeding Use: {pregnancy_text}"
        f"\n\nPediatric Use: {pediatric_text}"
        f"\n\nWarnings and Precautions: {warnings_text}"
        f"\n\nDrug Interactions: {interactions_text}"
        f"\n\nContraindications: {contraindications_text}"
    )

    # For combination products, we prepend a clear disclaimer so the model
    # (and any human reader) knows the clinical data comes from a combo product.
    if data_quality == "combination_product":
        combo_disclaimer = (
            f"NOTE: The following clinical data is sourced from a COMBINATION product "
            f"containing this ingredient alongside others (FDA product: {matched_openfda_name}), "
            "not this ingredient alone. Dosage and interaction specifics may not directly "
            "apply to a single-ingredient formulation."
        )
        content = (
            f"{combo_disclaimer}\n\n"
            f"{header_line}"
            f"{pharm_line}"
            f"{moa_line}"
            f"{route_line}"
            f"{clinical_section}"
            f"{brand_line}"
        )
    else:
        content = (
            f"{header_line}"
            f"{pharm_line}"
            f"{moa_line}"
            f"{route_line}"
            f"{clinical_section}"
            f"{brand_line}"
        )

    return content.strip()


# ---------------------------------------------------------------------------
# STEP 4 — Load already-completed clinical fetches for resumability
# ---------------------------------------------------------------------------

def load_already_fetched_clinical_fields(clinical_fields_jsonl_path: str) -> dict[str, dict]:
    """
    WHY THIS EXISTS:
        This script may take 10+ minutes to fetch 1,008 API calls. If the
        machine reboots, the internet drops, or we hit a sustained rate-limit
        pause, we don't want to start from scratch. By reading the output file
        line by line, we reconstruct a set of already-completed generics and
        skip them in the main loop.
    """
    already_fetched: dict[str, dict] = {}

    if not os.path.exists(clinical_fields_jsonl_path):
        logger.info("No existing clinical fields file found. Starting fresh.")
        return already_fetched

    with open(clinical_fields_jsonl_path, "r", encoding="utf-8") as file_handle:
        for line in file_handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                name = record.get("normalized_generic_name", "")
                if name:
                    already_fetched[name] = record
            except json.JSONDecodeError:
                # A truncated line from a previous interrupted run — skip it.
                continue

    logger.info(
        "Resuming: found %d already-fetched generics in clinical fields file.",
        len(already_fetched),
    )
    return already_fetched


# ---------------------------------------------------------------------------
# STEP 5 — Update one existing CKB row in the database (atomic per generic)
# ---------------------------------------------------------------------------

def update_clinical_knowledge_row(
    database_session: Session,
    normalized_generic_name: str,
    new_content_text: str,
    new_embedding_vector: list[float],
) -> bool:
    """
    WHY THIS EXISTS:
        We are UPDATING existing rows, not inserting new ones. The medications
        and drug_brand_aliases tables must NOT be touched in this step —
        those are already correct from 5.2e. Only the content and embedding
        in clinical_knowledge_base need to be refreshed.

        We wrap each update in its own commit so that a single bad update
        (e.g. embedding dimension mismatch, database timeout) doesn't
        roll back all previous successful updates.

    Returns:
        True if the update succeeded, False if it failed after rollback.
    """
    generic_sku_id = f"{GENERIC_SKU_PREFIX}{normalized_generic_name.upper()}"

    try:
        # We use a raw SQL UPDATE because SQLAlchemy ORM's session.query().update()
        # doesn't handle pgvector's binary serialization well for the Vector(768) column.
        # Raw SQL gives us full control over how the vector is passed.
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

    except Exception as update_error:
        database_session.rollback()
        logger.error(
            "FAILED to update CKB row for '%s' (sku: %s). Error: %s",
            normalized_generic_name,
            generic_sku_id,
            update_error,
        )
        return False


# ---------------------------------------------------------------------------
# MAIN — orchestrate the full patch pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    """
    WHY THIS EXISTS:
        This function is the director. It calls each helper in order, passing
        results between them, and produces a final summary. Reading this function
        top to bottom gives a complete picture of what the script does.
    """
    script_start_time = time.time()

    print("=" * 72)
    print("  5.2e-PATCH: CLINICAL FIELDS ENRICHMENT")
    print("=" * 72)

    # ======================================================================
    # PHASE 1: Load the existing openfda results to find MATCHED generics
    # ======================================================================
    logger.info("Phase 1: Loading existing OpenFDA results to identify MATCHED generics...")

    matched_records: list[dict] = []
    with open(OPENFDA_EXISTING_JSONL, "r", encoding="utf-8") as jsonl_file:
        for line in jsonl_file:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("status") == "MATCHED":
                matched_records.append(record)

    logger.info("Found %d MATCHED generics to enrich.", len(matched_records))

    # ======================================================================
    # PHASE 2: Load already-fetched clinical data (for resumability)
    # ======================================================================
    logger.info("Phase 2: Checking for already-fetched clinical fields (resumability)...")
    already_fetched_map = load_already_fetched_clinical_fields(CLINICAL_FIELDS_JSONL)

    generics_to_fetch = [
        r for r in matched_records
        if r["normalized_generic_name"] not in already_fetched_map
    ]
    logger.info(
        "%d already fetched (will reuse). %d remaining to fetch.",
        len(already_fetched_map),
        len(generics_to_fetch),
    )

    # ======================================================================
    # PHASE 3: Fetch full clinical labels from OpenFDA for remaining generics
    # ======================================================================
    logger.info("Phase 3: Fetching full clinical label data from OpenFDA API...")

    fetch_success_count = 0
    fetch_failure_list: list[str] = []

    with open(CLINICAL_FIELDS_JSONL, "a", encoding="utf-8") as output_file:
        for position, record in enumerate(generics_to_fetch):
            normalized_name = record["normalized_generic_name"]
            query_step = record["query_step_that_matched"]
            data_quality = record.get("data_quality", "single_ingredient")

            # Reconstruct the exact query that worked in 5.2f.
            query_result = reconstruct_query_for_generic(normalized_name, query_step)

            if query_result is None:
                # We couldn't reconstruct the query — log and skip.
                logger.warning("Could not reconstruct query for '%s' (step %s). Skipping.", normalized_name, query_step)
                fetch_failure_list.append(normalized_name)

                # Write a failure record so we don't retry this generic on resume.
                failure_record = {
                    "normalized_generic_name": normalized_name,
                    "fetch_status": "QUERY_RECONSTRUCTION_FAILED",
                    "dosage_and_administration": "",
                    "pregnancy_or_breastfeeding": "",
                    "pediatric_use": "",
                    "warnings": "",
                    "drug_interactions": "",
                    "contraindications": "",
                }
                output_file.write(json.dumps(failure_record) + "\n")
                output_file.flush()
                continue

            api_url, field_searched = query_result

            # Fetch the full label.
            clinical_fields = fetch_full_clinical_label(
                api_url=api_url,
                normalized_name=normalized_name,
                original_data_quality=data_quality,
            )

            if clinical_fields is None:
                # Fetch failed after all retries. Record this as a failure.
                fetch_failure_list.append(normalized_name)
                failure_record = {
                    "normalized_generic_name": normalized_name,
                    "fetch_status": "FETCH_FAILED",
                    "dosage_and_administration": "",
                    "pregnancy_or_breastfeeding": "",
                    "pediatric_use": "",
                    "warnings": "",
                    "drug_interactions": "",
                    "contraindications": "",
                }
                output_file.write(json.dumps(failure_record) + "\n")
                output_file.flush()
            else:
                # Success — mark and write to output file.
                clinical_fields["fetch_status"] = "SUCCESS"
                fetch_success_count += 1
                already_fetched_map[normalized_name] = clinical_fields
                output_file.write(json.dumps(clinical_fields) + "\n")
                output_file.flush()

            # Progress log every 100 fetches.
            if (position + 1) % 100 == 0 or (position + 1) == len(generics_to_fetch):
                elapsed = time.time() - script_start_time
                logger.info(
                    "Fetch progress: %d/%d | %d succeeded | %d failed | %.0fs elapsed",
                    position + 1,
                    len(generics_to_fetch),
                    fetch_success_count,
                    len(fetch_failure_list),
                    elapsed,
                )

    # Count total successes including already-fetched-from-prior-run.
    total_usable_clinical_records = sum(
        1 for r in already_fetched_map.values()
        if r.get("fetch_status") == "SUCCESS"
    )
    logger.info(
        "Phase 3 complete. Total usable clinical records (including prior runs): %d",
        total_usable_clinical_records,
    )

    # ======================================================================
    # PHASE 4: Build new content texts for all generics with clinical data
    # ======================================================================
    logger.info("Phase 4: Building enriched content texts...")

    # We'll need the openfda sub-block (for routes, pharm_class etc.) from
    # the original matched records. Build a quick lookup.
    original_record_by_name: dict[str, dict] = {
        r["normalized_generic_name"]: r for r in matched_records
    }

    # We'll also need known brand names from the CKB's existing metadata_payload.
    # Fetch those now in bulk rather than per-generic to reduce DB round-trips.
    logger.info("Phase 4a: Loading existing CKB metadata for brand names...")

    db_session = SessionLocal()
    existing_metadata_map: dict[str, dict] = {}
    try:
        rows = db_session.execute(
            sa_text("SELECT sku_id, metadata_payload FROM clinical_knowledge_base WHERE sku_id LIKE 'GENERIC_REF_%'")
        ).fetchall()
        for sku_id, payload in rows:
            # sku_id is like "GENERIC_REF_CEFIXIME" — extract the generic name.
            name_key = sku_id.replace(GENERIC_SKU_PREFIX, "").lower()
            existing_metadata_map[name_key] = payload or {}
    finally:
        db_session.close()

    # Also load the brand aliases for each generic from drug_brand_aliases,
    # capped at 20 per generic (we only use them for the content text sample).
    logger.info("Phase 4b: Loading brand name samples from drug_brand_aliases...")
    db_session = SessionLocal()
    brand_sample_map: dict[str, list[str]] = {}
    try:
        alias_rows = db_session.execute(
            sa_text(
                "SELECT sku_id, alias_text FROM drug_brand_aliases "
                "WHERE alias_type = 'brand_name' AND sku_id LIKE 'GENERIC_REF_%' "
                "ORDER BY sku_id, alias_text LIMIT 35000"
            )
        ).fetchall()
        for sku_id, alias_text in alias_rows:
            name_key = sku_id.replace(GENERIC_SKU_PREFIX, "").lower()
            if name_key not in brand_sample_map:
                brand_sample_map[name_key] = []
            if len(brand_sample_map[name_key]) < 20:
                brand_sample_map[name_key].append(alias_text)
    finally:
        db_session.close()

    # Now build enriched content for every generic that has a successful clinical fetch.
    generics_with_new_content: list[tuple[str, str, str]] = []
    # Each tuple is: (normalized_name, new_content_text, data_quality)

    for record in matched_records:
        normalized_name = record["normalized_generic_name"]
        data_quality = record.get("data_quality", "single_ingredient")
        matched_name = record.get("matched_openfda_name", "")

        clinical_data = already_fetched_map.get(normalized_name, {})
        if clinical_data.get("fetch_status") != "SUCCESS":
            # This generic's fetch failed — skip it (keep old content unchanged).
            continue

        # Pull the openfda sub-block from the original record (it has route/pharm class).
        original_openfda_block = record.get("raw_openfda_block") or {}
        route_strings = original_openfda_block.get("route", [])
        pharm_class_strings = original_openfda_block.get("pharm_class_epc", [])
        moa_strings = original_openfda_block.get("pharm_class_moa", [])

        # Get sample brand names for this generic.
        known_brands_sample = brand_sample_map.get(normalized_name, [])

        new_content = build_enriched_content_text(
            normalized_generic_name=normalized_name,
            matched_openfda_name=matched_name,
            data_quality=data_quality,
            clinical_fields=clinical_data,
            route_strings=route_strings,
            pharm_class_strings=pharm_class_strings,
            moa_strings=moa_strings,
            known_brand_names_sample=known_brands_sample,
        )

        generics_with_new_content.append((normalized_name, new_content, data_quality))

    logger.info(
        "Phase 4 complete. %d generics have enriched content ready for re-embedding.",
        len(generics_with_new_content),
    )

    # ======================================================================
    # PHASE 5: Load embedding model and batch-generate new embeddings
    # ======================================================================
    logger.info("Phase 5: Generating new embeddings for %d updated content texts...", len(generics_with_new_content))

    import torch
    from sentence_transformers import SentenceTransformer
    from tqdm import tqdm

    if torch.cuda.is_available():
        device_name = torch.cuda.get_device_name(0)
        device = "cuda"
        logger.info("GPU detected: %s. Using CUDA.", device_name)
    else:
        device = "cpu"
        logger.warning("No GPU. Using CPU — will be slower.")

    logger.info("Loading PubMedBERT model...")
    model = SentenceTransformer("NeuML/pubmedbert-base-embeddings", device=device)
    logger.info("Model ready on %s.", device)

    # Extract just the text strings for batch embedding.
    all_new_texts = [content for (_, content, _) in generics_with_new_content]

    embed_start = time.time()
    all_new_embeddings: list[list[float]] = []

    for batch_start in tqdm(range(0, len(all_new_texts), 128), desc="Embedding batches", unit="batch"):
        batch_end = min(batch_start + 128, len(all_new_texts))
        batch = all_new_texts[batch_start:batch_end]
        batch_embeddings = model.encode(batch, batch_size=128, show_progress_bar=False).tolist()
        all_new_embeddings.extend(batch_embeddings)

    embed_seconds = time.time() - embed_start
    logger.info("Embedding complete: %d vectors in %.1fs.", len(all_new_embeddings), embed_seconds)

    # ======================================================================
    # PHASE 6: Update each CKB row with new content + new embedding
    # ======================================================================
    logger.info("Phase 6: Updating clinical_knowledge_base rows...")

    db_session = SessionLocal()
    update_success_count = 0
    update_failure_list: list[str] = []

    try:
        for position, (normalized_name, new_content, _) in enumerate(generics_with_new_content):
            new_embedding = all_new_embeddings[position]

            success = update_clinical_knowledge_row(
                database_session=db_session,
                normalized_generic_name=normalized_name,
                new_content_text=new_content,
                new_embedding_vector=new_embedding,
            )

            if success:
                update_success_count += 1
            else:
                update_failure_list.append(normalized_name)

            if (position + 1) % 100 == 0 or (position + 1) == len(generics_with_new_content):
                logger.info(
                    "Update progress: %d/%d | %d succeeded | %d failed",
                    position + 1,
                    len(generics_with_new_content),
                    update_success_count,
                    len(update_failure_list),
                )
    finally:
        db_session.close()

    # ======================================================================
    # PHASE 7: Verify table counts are unchanged (medications + aliases)
    # ======================================================================
    logger.info("Phase 7: Verifying medications and drug_brand_aliases counts unchanged...")

    verify_session = SessionLocal()
    try:
        meds_count = verify_session.execute(sa_text("SELECT COUNT(*) FROM medications")).scalar()
        ckb_count = verify_session.execute(sa_text("SELECT COUNT(*) FROM clinical_knowledge_base")).scalar()
        aliases_count = verify_session.execute(sa_text("SELECT COUNT(*) FROM drug_brand_aliases")).scalar()
    finally:
        verify_session.close()

    # ======================================================================
    # PHASE 8: Pull before/after samples for the report
    # ======================================================================
    logger.info("Phase 8: Pulling before/after content samples for report...")

    # We'll pick cefixime, amoxycillin, and a third of interest.
    sample_names_for_report = ["cefixime", "amoxycillin", "paracetamol"]
    sample_report = {}

    report_session = SessionLocal()
    try:
        for sample_name in sample_names_for_report:
            sku_id = f"{GENERIC_SKU_PREFIX}{sample_name.upper()}"
            row = report_session.execute(
                sa_text("SELECT content FROM clinical_knowledge_base WHERE sku_id = :sku"),
                {"sku": sku_id}
            ).fetchone()
            sample_report[sample_name] = row[0] if row else "NOT FOUND"
    finally:
        report_session.close()

    total_elapsed = time.time() - script_start_time

    # ======================================================================
    # FINAL SUMMARY REPORT
    # ======================================================================
    print("\n" + "=" * 72)
    print("  PATCH COMPLETE — 5.2e-PATCH REPORT")
    print("=" * 72)

    print(f"\nStep 1 — Query reconstruction:")
    print(f"  Total MATCHED generics:    1008")
    print(f"  Query reconstruction failures: {len([n for n in fetch_failure_list])}")

    print(f"\nStep 2 — Fetch results:")
    print(f"  Successfully fetched (this run): {fetch_success_count}")
    print(f"  Total usable (including prior): {total_usable_clinical_records}")
    print(f"  Fetch failures: {len(fetch_failure_list)}")
    if fetch_failure_list:
        for name in fetch_failure_list[:10]:
            print(f"    - {name}")
        if len(fetch_failure_list) > 10:
            print(f"    ... and {len(fetch_failure_list) - 10} more")

    print(f"\nStep 3/4 — Before vs after content samples:")
    for sample_name in sample_names_for_report:
        print(f"\n  [{sample_name.upper()} — current content after update]")
        content_snippet = sample_report.get(sample_name, "NOT FOUND")
        print(f"  {content_snippet[:600]}...")

    print(f"\nUpdate results:")
    print(f"  Rows updated in clinical_knowledge_base: {update_success_count}")
    if update_failure_list:
        print(f"  Update failures ({len(update_failure_list)}):")
        for name in update_failure_list:
            print(f"    - {name}")
    else:
        print(f"  Update failures: NONE")

    print(f"\nTable counts (should not have changed):")
    print(f"  medications:            1614 (expected) -> {meds_count} (actual)")
    print(f"  clinical_knowledge_base: 1596 (expected) -> {ckb_count} (actual)")
    print(f"  drug_brand_aliases:  251113 (expected) -> {aliases_count} (actual)")

    print(f"\nTiming:")
    print(f"  Embedding time:     {embed_seconds:.1f}s")
    print(f"  Total script time:  {total_elapsed:.1f}s")
    print("=" * 72)


if __name__ == "__main__":
    main()
