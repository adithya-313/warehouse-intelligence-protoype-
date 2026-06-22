import pandas as pd
import numpy as np
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Beginner Note: In a real production system, this mapping would live in a database table
# or be powered by a fuzzy-matching NLP model. For this MVP, we use a static dictionary
# to demonstrate the concept of normalizing brand names to canonical molecules.
API_NORMALIZATION_MAP = {
    "dolo 650": "paracetamol",
    "calpol 500": "paracetamol",
    "crocin advance": "paracetamol",
    "augmentin 625": "amoxicillin_clavulanate",
    "moxikind-cv": "amoxicillin_clavulanate",
    "allegra 120": "fexofenadine"
}

def normalize_brand_to_api(brand_name: str) -> str:
    """
    Converts a commercial brand name into its Active Pharmaceutical Ingredient (API).
    """
    if not isinstance(brand_name, str):
        return "unknown_api"
        
    clean_name = brand_name.strip().lower()
    return API_NORMALIZATION_MAP.get(clean_name, "unknown_api")

def process_legacy_erp_csv(file_buffer) -> Dict[str, np.ndarray]:
    """
    Parses a CSV export from Marg ERP or Vyapaar, normalizes the items,
    and formats the historical data into 1D NumPy arrays for Chronos-2 ML training.
    
    Expected CSV Columns: 'date', 'item_name', 'quantity_sold'
    """
    try:
        # 1. Load the CSV data into a Pandas DataFrame
        df = pd.read_csv(file_buffer)
        
        # Validate required columns exist
        required_columns = {'date', 'item_name', 'quantity_sold'}
        if not required_columns.issubset(df.columns):
            raise ValueError(f"CSV must contain columns: {required_columns}")

        # 2. Normalize the brand names to canonical APIs
        # Beginner Note: We do this so the ML model learns the demand for 'Paracetamol'
        # as a whole, rather than splitting its learning across Dolo, Calpol, and Crocin.
        df['canonical_api'] = df['item_name'].apply(normalize_brand_to_api)
        
        # 3. Convert dates to actual datetime objects so we can sort them chronologically
        df['date'] = pd.to_datetime(df['date'])
        
        # 4. Group by the API and the Date, summing up the total quantity sold per day
        daily_sales = df.groupby(['canonical_api', 'date'])['quantity_sold'].sum().reset_index()
        
        # Sort chronologically to ensure the time-series data is in the correct order
        daily_sales = daily_sales.sort_values('date')
        
        # 5. Format the data for the Chronos-2 LoRA worker
        chronos_training_data = {}
        
        # Loop through each unique API we found
        for api in daily_sales['canonical_api'].unique():
            # Filter the data for just this API
            api_data = daily_sales[daily_sales['canonical_api'] == api]
            
            # Extract the 'quantity_sold' column and convert it to a 1D NumPy array of floats
            # Beginner Note: This is the exact mathematical format the ML model requires.
            time_series_array = api_data['quantity_sold'].astype(float).to_numpy()
            
            chronos_training_data[api] = time_series_array
            
        logger.info(f"Successfully processed ERP data. Extracted {len(chronos_training_data)} canonical APIs.")
        return chronos_training_data
        
    except Exception as e:
        logger.error(f"Failed to process legacy ERP CSV: {e}")
        raise
