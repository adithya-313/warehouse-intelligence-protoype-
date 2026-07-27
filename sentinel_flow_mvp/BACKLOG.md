# Backlog

## Multi-Drug Query Detection
- **Issue:** Users frequently ask questions combining multiple drugs (e.g. "is it safe to take metoprolol and amlodipine together").
- **Current Behavior:** The drug resolver groups all words in the query into a single candidate list, and takes the top 3 fuzzy matches globally. When multiple valid drugs are present, it either surfaces both as a "disambiguation" list, or one drug "out-scores" the other, causing the second drug to be silently dropped. The ClinicalSafetyJudge then only evaluates the single drug that survived, bypassing the interaction check.
- **Proposed Fix:** Modify the `drug_resolver.py` pipeline to detect when a query contains *multiple disjoint high-confidence matches* (e.g., METOPROLOL at score 1.0 and AMLODIPINE at score 1.0). Instead of treating this as an ambiguous reference to a single drug (triggering disambiguation), it should transition to a `multi_drug_interaction` intent and pass both SKUs to the safety engine for contraindication checks.

## SKU Normalization/Canonicalization Mismatch
- **Issue:** The regex-based `extracted_sku` produces mismatched formatting compared to the real database SKU canonicalization (e.g. `extract_sku` produces `PN-40` while the actual database SKU is `PN40`).
- **Current Behavior:** We cannot currently trust `extracted_sku` as a safe short-circuit source for the `drug_resolver` because passing pseudo-SKUs like `PN-40` downstream breaks routing logic and exposes latent bugs when database records aren't found. We are currently using only `payload.sku_id` (the trusted frontend input) to bypass the fuzzy matching.
- **Proposed Fix:** Centralize SKU normalization so the sanitizer and the DB resolver use the exact same canonicalization logic. This is part of the same root-cause family as the `translate_to_sku` N+1 backlog item — there are multiple disconnected sources of truth for what a SKU string looks like.
