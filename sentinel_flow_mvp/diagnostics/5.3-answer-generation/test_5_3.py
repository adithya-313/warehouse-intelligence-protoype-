import asyncio
import logging
import json
import os
from sqlalchemy.orm import Session
from app.api.v1.knowledge_base import ask_clinical_assistant, RAGQueryRequest
from app.infrastructure.database import get_db

# Create directories
os.makedirs("diagnostics/5.3-answer-generation", exist_ok=True)

async def run_query(query_text: str, log_filename: str):
    # Setup logger for this specific run
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        
    fh = logging.FileHandler(f"diagnostics/5.3-answer-generation/{log_filename}", mode='w')
    fh.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    
    # Console handler just for us to see progress
    ch = logging.StreamHandler()
    ch.setLevel(logging.ERROR)
    logger.addHandler(ch)

    print(f"Running query: '{query_text}' -> {log_filename}")
    
    # Run the query
    db: Session = next(get_db())
    request = RAGQueryRequest(query=query_text)
    
    try:
        result = await ask_clinical_assistant(request, db=db)
        logger.info(f"[DIAG-5.3] FINAL RESULT:\n{json.dumps(result, indent=2)}")
    except Exception as e:
        logger.error(f"[DIAG-5.3] EXCEPTION: {e}")
    finally:
        db.close()
        logger.removeHandler(fh)
        fh.close()

async def main():
    queries = [
        ("paracetamol overdose symptoms", "query1_paracetamol_overdose.log"),
        ("Augmentin vs Amoxyclav difference", "query2_augmentin_vs_amoxyclav.log"),
        ("tell me about nimesulide dosage", "query3_nimesulide_dosage.log")
    ]
    
    for q, f in queries:
        await run_query(q, f)

if __name__ == "__main__":
    asyncio.run(main())
