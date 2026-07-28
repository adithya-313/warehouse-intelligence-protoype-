"""
READ-ONLY diagnostic: content length audit of clinical_knowledge_base.
No writes, no modifications. Query only.
"""
import os, statistics, re
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://sentinel:sentinel@db:5432/sentinel_db")
engine = create_engine(DATABASE_URL)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Content length distribution for the 1,008 real matched generics
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("STEP 1 — Content length distribution (openfda_generic_reference, non-identity_only)")
print("="*70)

with engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT sku_id,
               metadata_payload->>'generic_name' AS generic_name,
               length(content) AS content_len
        FROM   clinical_knowledge_base
        WHERE  metadata_payload->>'source' = 'openfda_generic_reference'
          AND  (metadata_payload->>'data_quality') != 'identity_only'
        ORDER  BY content_len ASC
    """)).fetchall()

lengths = [r.content_len for r in rows]
total = len(lengths)
print(f"\nTotal matched-generic rows: {total}")

if lengths:
    print(f"Min    : {min(lengths):,} chars")
    print(f"Max    : {max(lengths):,} chars")
    print(f"Median : {int(statistics.median(lengths)):,} chars")
    print(f"Mean   : {int(statistics.mean(lengths)):,} chars")

    under3k  = sum(1 for l in lengths if l < 3_000)
    k3_to_10k = sum(1 for l in lengths if 3_000 <= l < 10_000)
    over10k  = sum(1 for l in lengths if l >= 10_000)
    print(f"\nDistribution:")
    print(f"  < 3,000 chars   : {under3k:4d}  ({100*under3k/total:.1f}%)")
    print(f"  3,000–10,000    : {k3_to_10k:4d}  ({100*k3_to_10k/total:.1f}%)")
    print(f"  > 10,000        : {over10k:4d}  ({100*over10k/total:.1f}%)")

    print("\nBottom 20 shortest records:")
    for i, r in enumerate(rows[:20], 1):
        print(f"  {i:2d}. {r.generic_name or r.sku_id:<40s}  {r.content_len:>6,} chars")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Section-presence check on ~30-record sample spread across distribution
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("STEP 2 — Missing-section analysis on spread sample (~30 records)")
print("="*70)

SECTION_PATTERNS = {
    "Adverse Reactions / Side Effects": re.compile(
        r"adverse reaction|side effect", re.IGNORECASE),
    "Dosage and Administration": re.compile(
        r"dosage|administration|dose|directions", re.IGNORECASE),
    "Contraindications": re.compile(
        r"contraindic", re.IGNORECASE),
    "Warnings": re.compile(
        r"warning|caution|precaution", re.IGNORECASE),
    "Pregnancy / Pediatric Use": re.compile(
        r"pregnan|pediatric|breast.?feed|nursing", re.IGNORECASE),
    "Drug Interactions": re.compile(
        r"drug interaction|interaction", re.IGNORECASE),
}

with engine.connect() as conn:
    all_rows_full = conn.execute(text("""
        SELECT sku_id,
               metadata_payload->>'generic_name' AS generic_name,
               content,
               length(content) AS content_len
        FROM   clinical_knowledge_base
        WHERE  metadata_payload->>'source' = 'openfda_generic_reference'
          AND  (metadata_payload->>'data_quality') != 'identity_only'
        ORDER  BY content_len ASC
    """)).fetchall()

all_rows_full = list(all_rows_full)
n = len(all_rows_full)

# Pick ~30 spread evenly across the sorted list, always include paracetamol
import math
step = max(1, n // 28)
sample_indices = list(range(0, n, step))[:30]

# Find paracetamol index
para_idx = next((i for i, r in enumerate(all_rows_full)
                 if "paracetamol" in (r.generic_name or "").lower()
                 or "GENERIC_REF_PARACETAMOL" in r.sku_id), None)
if para_idx is not None and para_idx not in sample_indices:
    sample_indices.append(para_idx)

sample = [all_rows_full[i] for i in sorted(set(sample_indices))]
print(f"\nSample size: {len(sample)} records (spread across full distribution)")

section_missing = {k: 0 for k in SECTION_PATTERNS}
print(f"\n{'Drug':<35} {'Len':>7}  {'AR':>3} {'DA':>3} {'CI':>3} {'WN':>3} {'PG':>3} {'DI':>3}")
print("-"*75)

section_keys = list(SECTION_PATTERNS.keys())
short_keys   = ["AR","DA","CI","WN","PG","DI"]

for r in sample:
    c = r.content or ""
    present = {k: bool(pat.search(c)) for k, pat in SECTION_PATTERNS.items()}
    for k in section_keys:
        if not present[k]:
            section_missing[k] += 1
    flags = ["✓" if present[k] else "✗" for k in section_keys]
    name = (r.generic_name or r.sku_id)[:34]
    marker = " ← PARACETAMOL" if ("paracetamol" in (r.generic_name or "").lower() or "GENERIC_REF_PARACETAMOL" in r.sku_id) else ""
    print(f"  {name:<34} {r.content_len:>7,}  {'  '.join(flags)}{marker}")

print(f"\nSection missing rates across {len(sample)} sampled records:")
for k, sk in zip(section_keys, short_keys):
    pct = 100.0 * section_missing[k] / len(sample)
    print(f"  {k:<40s}: {section_missing[k]:3d}/{len(sample)}  ({pct:.1f}% missing)")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Identity-only 577 consistency check
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("STEP 3 — Identity-only 577 consistency check")
print("="*70)

# Expected pattern: "Not available" / "FDA data not available" style content
IDENTITY_OK_PAT = re.compile(
    r"not (specified|available)|identity.only|no (fda|data)|N/A", re.IGNORECASE)

with engine.connect() as conn:
    id_rows = conn.execute(text("""
        SELECT sku_id,
               metadata_payload->>'generic_name' AS generic_name,
               content,
               length(content) AS content_len
        FROM   clinical_knowledge_base
        WHERE  metadata_payload->>'source' = 'openfda_generic_reference'
          AND  metadata_payload->>'data_quality' = 'identity_only'
        ORDER  BY content_len DESC
    """)).fetchall()

id_rows = list(id_rows)
print(f"\nTotal identity-only rows: {len(id_rows)}")

if id_rows:
    id_lens = [r.content_len for r in id_rows]
    print(f"Min content length : {min(id_lens):,}")
    print(f"Max content length : {max(id_lens):,}")
    print(f"Median             : {int(statistics.median(id_lens)):,}")

    # Classify each: does it match expected honest-disclosure pattern?
    ok_count    = 0
    broken_list = []
    long_list   = []

    for r in id_rows:
        c = r.content or ""
        # An identity-only record should NOT have substantive clinical data
        # The nimesulide pattern we verified: has "Not specified in FDA label"
        has_honest_disclosure = IDENTITY_OK_PAT.search(c)
        # Unexpected: contains real clinical sections that identity-only shouldn't have
        has_real_clinical = re.search(
            r"adverse reaction|contraindic|dosage and administration",
            c, re.IGNORECASE)

        if has_honest_disclosure and not has_real_clinical:
            ok_count += 1
        elif has_real_clinical:
            # These have actual data — they may be misclassified
            long_list.append(r)
        else:
            broken_list.append(r)

    print(f"\nConsistently honest-disclosure (expected pattern) : {ok_count}")
    print(f"Possibly misclassified (have real clinical data)   : {len(long_list)}")
    print(f"Anomalous (neither pattern)                        : {len(broken_list)}")

    if long_list:
        print(f"\nTop 10 identity-only records with real clinical data (possibly misclassified):")
        for r in long_list[:10]:
            print(f"  {(r.generic_name or r.sku_id):<40s}  {r.content_len:>6,} chars")

    if broken_list:
        print(f"\nAnomalous identity-only records (first 10):")
        for r in broken_list[:10]:
            snippet = (r.content or "")[:120].replace("\n"," ")
            print(f"  {(r.generic_name or r.sku_id):<35s}  len={r.content_len}  snippet: {snippet!r}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Root cause evidence gathering
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("STEP 4 — Root cause evidence")
print("="*70)

# Compare field-level content between a short and a long record to see
# which structured fields are populated vs missing
with engine.connect() as conn:
    examples = conn.execute(text("""
        SELECT sku_id,
               metadata_payload->>'generic_name' AS generic_name,
               metadata_payload->>'fda_name'     AS fda_name,
               length(content)                   AS content_len,
               content
        FROM   clinical_knowledge_base
        WHERE  metadata_payload->>'source' = 'openfda_generic_reference'
          AND  (metadata_payload->>'data_quality') != 'identity_only'
        ORDER  BY content_len ASC
        LIMIT  5
    """)).fetchall()

    long_examples = conn.execute(text("""
        SELECT sku_id,
               metadata_payload->>'generic_name' AS generic_name,
               metadata_payload->>'fda_name'     AS fda_name,
               length(content)                   AS content_len,
               content
        FROM   clinical_knowledge_base
        WHERE  metadata_payload->>'source' = 'openfda_generic_reference'
          AND  (metadata_payload->>'data_quality') != 'identity_only'
        ORDER  BY content_len DESC
        LIMIT  3
    """)).fetchall()

SECTION_MARKERS = [
    ("Routes of Administration",       re.compile(r"Routes of Administration",    re.IGNORECASE)),
    ("Dosage and Administration",      re.compile(r"Dosage and Administration",   re.IGNORECASE)),
    ("Adverse Reactions/Side Effects", re.compile(r"adverse reaction|side effect",re.IGNORECASE)),
    ("Warnings and Precautions",       re.compile(r"Warning",                     re.IGNORECASE)),
    ("Contraindications",              re.compile(r"Contraindic",                 re.IGNORECASE)),
    ("Pregnancy/Pediatric",            re.compile(r"Pregnan|Pediatric",           re.IGNORECASE)),
    ("Drug Interactions",              re.compile(r"Drug Interaction",            re.IGNORECASE)),
]

def section_audit(name, content, length):
    print(f"\n  Drug: {name}  ({length:,} chars)")
    for label, pat in SECTION_MARKERS:
        present = "PRESENT" if pat.search(content or "") else "MISSING"
        print(f"    {label:<40s}: {present}")

print("\n-- Shortest 5 records (possible truncation / sparse FDA label) --")
for r in examples:
    section_audit(r.generic_name or r.sku_id, r.content, r.content_len)

print("\n-- Longest 3 records (full FDA data baseline) --")
for r in long_examples:
    section_audit(r.generic_name or r.sku_id, r.content, r.content_len)

# Paracetamol specifically
with engine.connect() as conn:
    para = conn.execute(text("""
        SELECT sku_id, metadata_payload->>'generic_name' AS generic_name,
               length(content) AS content_len, content
        FROM   clinical_knowledge_base
        WHERE  sku_id = 'GENERIC_REF_PARACETAMOL'
        LIMIT 1
    """)).fetchone()
if para:
    print("\n-- PARACETAMOL specifically --")
    section_audit(para.generic_name or para.sku_id, para.content, para.content_len)

print("\n" + "="*70)
print("DONE — no data was modified.")
print("="*70)
