import sys
import os
import numpy as np
from sqlalchemy import create_engine, text

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import get_application_settings
from chronos import ChronosPipeline
import torch

def mean_absolute_error(y_true, y_pred):
    return np.mean(np.abs(y_true - y_pred))

def mean_absolute_percentage_error(y_true, y_pred):
    # Avoid division by zero
    mask = y_true != 0
    return np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100

def main():
    settings = get_application_settings()
    engine = create_engine(settings.database_url)
    
    skus = [
        {"id": "SKU-NV-4070S", "profile": "High Volume"},
        {"id": "SKU-IN-285K", "profile": "Mid Volume"},
        {"id": "SKU-NV-5090", "profile": "High Volatility"}
    ]
    
    pipeline = ChronosPipeline.from_pretrained(
        "amazon/chronos-t5-mini",
        device_map="auto",
        torch_dtype=torch.bfloat16
    )
    
    results = []
    total_mape = []

    print("| SKU ID | Profile | MAE (Units) | MAPE (%) |")
    print("|---|---|---|---|")
    
    with engine.connect() as conn:
        for sku in skus:
            # Query 120 days of historical data, ordered by time
            query = text("""
                SELECT inventory_count 
                FROM inventory_telemetry 
                WHERE sku_id = :sku_id 
                ORDER BY recorded_at ASC 
                LIMIT 120
            """)
            
            rows = conn.execute(query, {"sku_id": sku["id"]}).fetchall()
            data = [float(row[0]) for row in rows]
            
            if len(data) < 120:
                print(f"| {sku['id']} | {sku['profile']} | Not enough data | N/A |")
                continue
                
            # Split: 90 days context, 30 days ground truth
            context = np.array(data[:90])
            ground_truth = np.array(data[90:120])
            
            # Predict 30 days
            context_tensor = torch.tensor(context).unsqueeze(0)
            forecast = pipeline.predict(context_tensor, prediction_length=30)
            
            if isinstance(forecast[0], torch.Tensor):
                try:
                    forecast_array = forecast[0].median(dim=0).values.float().numpy()
                except Exception:
                    forecast_array = forecast[0].mean(dim=0).float().numpy()
            else:
                forecast_array = np.array(forecast[0])
            
            mae = mean_absolute_error(ground_truth, forecast_array)
            mape = mean_absolute_percentage_error(ground_truth, forecast_array)
            
            total_mape.append(mape)
            
            print(f"| {sku['id']} | {sku['profile']} | {mae:.2f} | {mape:.2f}% |")
            
    print(f"\n**Overall System MAPE:** {np.mean(total_mape):.2f}%")

if __name__ == "__main__":
    main()
