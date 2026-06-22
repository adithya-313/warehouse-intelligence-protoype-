from fastapi import APIRouter, UploadFile, File, HTTPException
from app.services.erp_bridge_service import process_legacy_erp_csv
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/upload-legacy-csv", status_code=202)
async def upload_legacy_erp_data(file: UploadFile = File(...)):
    """
    Endpoint for pharmacies to upload their historical CSV exports from Marg ERP or Vyapaar.
    The data is normalized and staged for overnight Chronos-2 LoRA fine-tuning.
    """
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")
        
    try:
        # Pass the file directly to our Pandas ETL service
        # Beginner Note: file.file is the actual byte stream of the uploaded file
        training_arrays = process_legacy_erp_csv(file.file)
        
        # In a full production system, we would now save these NumPy arrays to a 
        # Vector DB or trigger a Celery background task to start the LoRA training.
        # For now, we acknowledge successful parsing.
        
        return {
            "status": "accepted",
            "message": "Legacy data parsed and normalized successfully.",
            "apis_extracted": list(training_arrays.keys()),
            "data_points_staged": sum(len(arr) for arr in training_arrays.values())
        }
        
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error in ERP upload endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during data processing.")
