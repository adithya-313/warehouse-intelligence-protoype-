"""
Clinical Safety Rule Engine (The Judge).

Beginner Note:
    This file is the DETERMINISTIC safety gate that runs BEFORE the LLM.
    We call it "The Judge" because it makes a binary decision:
    ALLOW or BLOCK.

    Why do we need a Judge BEFORE the AI?
    Because AI models can be creative — and in pharmacy, creativity kills.
    If a pregnant patient asks about a Category X drug, we do NOT want
    the AI to "accidentally" suggest it's safe because the context was
    ambiguous.

    The Judge is a set of PURE IF/ELSE rules that are:
    - 100% deterministic (same inputs always produce same output)
    - 100% auditable (every decision has a reason code)
    - Zero AI involvement (no hallucinations possible)

    Think of it like a circuit breaker in your house:
    When current exceeds the safe limit, the breaker TRIPS instantly
    and cuts power. No discussion, no negotiation. The Judge trips
    before the LLM ever gets a chance to respond.
"""

import logging

logger = logging.getLogger(__name__)


# =====================================================================
# CATEGORY X / D — PREGNANCY CONTRAINDICATION LIST
# =====================================================================
# Beginner Note: These are the FDA / CDSCO pregnancy safety categories
# that mean "DO NOT DISPENSE to a pregnant patient."
#
# Category X = Studies in animals or humans have demonstrated fetal
#              abnormalities. The risk clearly outweighs any benefit.
#              NEVER dispense to a pregnant patient.
# Category D = Positive evidence of human fetal risk, but the benefits
#              may be acceptable in certain circumstances (e.g., to
#              treat a life-threatening condition). We still BLOCK by
#              default and require a senior pharmacist override.
PREGNANCY_CONTRAINDICATED_CATEGORIES = {"X", "D"}


class ClinicalSafetyJudge:
    """
    Deterministic Rule Engine for clinical safety decisions.

    This class evaluates a set of patient intents against the retrieved
    medication safety data and returns a structured verdict.

    The verdict is a dict with three keys:
        - is_safe (bool):       True if no rule was violated.
        - lock_reason (str | None):  The reason code if blocked.
        - triggered_rule (str | None): Human-readable name of the rule
                                       that triggered the block.

    Example output:
        {"is_safe": False,
         "lock_reason": "CRITICAL_PREGNANCY_CONTRAINDICATION",
         "triggered_rule": "Pregnancy Category X/D Check"}
    """

    def evaluate_safety(
        self,
        intents: dict,
        retrieved_records: list[dict],
    ) -> dict:
        """
        Evaluate whether the requested medication is safe to dispense
        based on the patient's intents and the medication's safety data.

        Parameters:
            intents: A dict of boolean flags extracted by the QuerySanitizer.
                     Expected keys: 'pregnancy', 'pediatric', 'substitute',
                     'objective'. We only inspect 'pregnancy' and 'pediatric'.
            retrieved_records: A list of dicts, each representing a retrieved
                               clinical record. Each dict SHOULD contain:
                               - 'sku_id' (str)
                               - 'pregnancy_category' (str | None)
                               - 'pediatric_age_threshold_months' (int | None)
                               If the key is missing, we skip that record
                               (no assumption of safety — we just move on).

        Returns:
            A verdict dict with keys:
                is_safe (bool)
                lock_reason (str | None)
                triggered_rule (str | None)
        """
        # =====================================================================
        # STEP 1: CHECK PREGNANCY SAFETY
        # =====================================================================
        # If the patient is pregnant (intent detected by QuerySanitizer),
        # we check EVERY retrieved record for a Category X or D flag.
        # A single X or D flag is enough to BLOCK the entire transaction.

        if intents.get("pregnancy"):
            logger.info(
                "ClinicalSafetyJudge: Pregnancy intent detected. "
                "Scanning records for Category X or D contraindications."
            )

            for record in retrieved_records:
                # Get the pregnancy category from the record.
                # If the key is missing or None, we skip it — that
                # medication simply hasn't been classified yet.
                pregnancy_category = record.get("pregnancy_category")

                if pregnancy_category and pregnancy_category.upper() in PREGNANCY_CONTRAINDICATED_CATEGORIES:
                    sku_id = record.get("sku_id", "UNKNOWN")
                    logger.warning(
                        f"ClinicalSafetyJudge: BLOCKED — SKU {sku_id} "
                        f"has pregnancy category '{pregnancy_category}' "
                        f"which is contraindicated for pregnant patients."
                    )

                    return {
                        "is_safe": False,
                        "lock_reason": "CRITICAL_PREGNANCY_CONTRAINDICATION",
                        "triggered_rule": "Pregnancy Category X/D Check",
                    }

        # =====================================================================
        # STEP 2: CHECK PEDIATRIC AGE SAFETY
        # =====================================================================
        # If the patient is a child (pediatric intent detected), we check
        # if the medication has a minimum age threshold. If the patient's
        # age is below that threshold, we BLOCK.
        #
        # Since the /ask endpoint does NOT currently collect patient age,
        # we default to patient_age_months = 0 (newborn). This is the
        # safest possible assumption — a newborn should not receive adult
        # medication without a pharmacist review.
        #
        # Future enhancement: When the frontend sends patient age in the
        # request, we will use that value here.

        if intents.get("pediatric"):
            # Assume the most vulnerable age (0 months = newborn)
            # unless the frontend provides actual patient data.
            patient_age_months = intents.get("patient_age_months", 0)

            logger.info(
                f"ClinicalSafetyJudge: Pediatric intent detected. "
                f"Patient age assumed {patient_age_months} months. "
                "Scanning records for age threshold violations."
            )

            for record in retrieved_records:
                age_threshold = record.get("pediatric_age_threshold_months")

                if age_threshold is not None and patient_age_months < age_threshold:
                    sku_id = record.get("sku_id", "UNKNOWN")
                    logger.warning(
                        f"ClinicalSafetyJudge: BLOCKED — SKU {sku_id} "
                        f"requires minimum age of {age_threshold} months, "
                        f"but patient is only {patient_age_months} months old."
                    )

                    return {
                        "is_safe": False,
                        "lock_reason": "PEDIATRIC_AGE_VIOLATION",
                        "triggered_rule": "Pediatric Age Threshold Check",
                    }

        # =====================================================================
        # STEP 3: DEFAULT — ALL CLEAR
        # =====================================================================
        # If no rules were violated, the transaction is safe to proceed.
        # The LLM narrator will generate a detailed explanation.

        logger.info("ClinicalSafetyJudge: All safety checks passed. Transaction ALLOWED.")

        return {
            "is_safe": True,
            "lock_reason": None,
            "triggered_rule": None,
        }
