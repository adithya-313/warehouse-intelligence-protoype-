"""
READ-ONLY pre-check: identify the precise boundary between "broken empty" records
and "short but legitimately complete" records.
No writes. Output only.
"""
import os, re
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://sentinel:sentinel@db:5432/sentinel_db")
engine = create_engine(DATABASE_URL)

SECTION_PATTERNS = {
    "Routes of Administration": re.compile(r"Routes of Administration", re.IGNORECASE),
    "Dosage and Administration": re.compile(r"dosage|administration|dose|directions", re.IGNORECASE),
    "Adverse Reactions / Side Effects": re.compile(r"adverse reaction|side effect", re.IGNORECASE),
    "Warnings": re.compile(r"warning|caution|precaution", re.IGNORECASE),
    "Pregnancy / Pediatric Use": re.compile(r"pregnan|pediatric|breast.?feed", re.IGNORECASE),
    "Drug Interactions": re.compile(r"drug interaction|interaction", re.IGNORECASE),
    "Contraindications": re.compile(r"contraindic", re.IGNORECASE),
}

with engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT sku_id,
               metadata_payload->>'generic_name' AS generic_name,
               length(content) AS content_len,
               content
        FROM   clinical_knowledge_base
        WHERE  metadata_payload->>'source' = 'openfda_generic_reference'
          AND  (metadata_payload->>'data_quality') != 'identity_only'
        ORDER  BY content_len ASC
        LIMIT  60
    """)).fetchall()

print(f"\nFirst 60 shortest non-identity_only records — section presence:\n")
print(f"{'#':>3}  {'Drug':<40} {'Len':>7}  Sections present")
print("-"*90)

confirmed_broken = []

for i, r in enumerate(rows, 1):
    c = r.content or ""
    sections = [k[:3] for k, pat in SECTION_PATTERNS.items() if pat.search(c)]
    missing_count = len(SECTION_PATTERNS) - len(sections)
    all_missing = missing_count == len(SECTION_PATTERNS)
    name = r.generic_name or r.sku_id
    
    flag = " ← ALL MISSING" if all_missing else ""
    print(f"{i:>3}. {name:<40} {r.content_len:>7,}  {', '.join(sections) if sections else 'NONE'}{flag}")
    
    if all_missing:
        confirmed_broken.append((r.sku_id, name, r.content_len))

print(f"\n{'='*60}")
print(f"CONFIRMED BROKEN RECORDS (all sections missing):")
print(f"{'='*60}")
for sku, name, length in confirmed_broken:
    print(f"  SKU: {sku:<50}  name: {name:<30}  len: {length}")
print(f"\nTotal confirmed broken: {len(confirmed_broken)}")
