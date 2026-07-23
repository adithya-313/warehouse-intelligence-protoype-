import logging
import time
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session
from sentence_transformers import SentenceTransformer
import torch

from app.infrastructure.database import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def build_corrected_content(generic_name, brands):
    disclaimer = (
        f"FDA data exists for this drug under a different name/formulation "
        f"than our automated search could locate — manual lookup recommended."
    )
    brand_line = ""
    if brands:
        brand_line = f"\n\nKnown Indian Brand Names (sample): {', '.join(brands[:20])}"
    return f"Drug: {generic_name.upper()}\n\n{disclaimer}{brand_line}".strip()

def main():
    db_session = SessionLocal()
    generic_name = "abemaciclib"
    sku_id = f"GENERIC_REF_{generic_name.upper()}"
    
    # 1. Fetch brands
    rows = db_session.execute(
        sa_text(
            "SELECT alias_text FROM drug_brand_aliases "
            "WHERE sku_id = :sku_id AND alias_type = 'brand_name' "
            "ORDER BY alias_text LIMIT 20"
        ),
        {"sku_id": sku_id}
    ).fetchall()
    brands = [row[0] for row in rows]
    
    # 2. Build content
    new_content = build_corrected_content(generic_name, brands)
    logging.info(f"New content:\n{new_content}")
    
    # 3. Embed
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer("NeuML/pubmedbert-base-embeddings", device=device)
    new_embedding = model.encode(new_content).tolist()
    
    # 4. Update DB
    db_session.execute(
        sa_text(
            "UPDATE clinical_knowledge_base "
            "SET content = :content, embedding = :embedding "
            "WHERE sku_id = :sku_id"
        ),
        {
            "content": new_content,
            "embedding": str(new_embedding),
            "sku_id": sku_id,
        }
    )
    db_session.commit()
    logging.info("Successfully updated abemaciclib.")
    db_session.close()

if __name__ == "__main__":
    main()
