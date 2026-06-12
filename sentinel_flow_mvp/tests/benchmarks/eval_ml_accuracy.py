import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import torch
import time
import numpy as np
import json
from app.infrastructure.database import SessionLocal
from app.infrastructure.models import TelemetryModel
from chronos import ChronosPipeline

# --- CONFIGURATION ---
TARGET_SUPPLIER = "NVIDIA Corporation"
CONTEXT_LENGTH = 90
PREDICTION_LENGTH = 5
NUM_BACKTEST_WINDOWS = 10  # Number of historical points to test

def calculate_mape(actual, predicted):
    """Calculates Mean Absolute Percentage Error. Handles zero-division safely."""
    actual, predicted = np.array(actual), np.array(predicted)
    mask = actual != 0
    if not mask.any():
        return 0.0
    return np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])) * 100

def calculate_mae(actual, predicted):
    """Calculates Mean Absolute Error."""
    return np.mean(np.abs(np.array(actual) - np.array(predicted)))

def run_backtest():
    print(f"🧠 INITIATING ML BACKTESTING FOR SUPPLIER: {TARGET_SUPPLIER}...")
    db = SessionLocal()
    
    try:
        # 1. Fetch the entire historical timeline for the target supplier ordered chronologically
        records = db.query(TelemetryModel).filter(
            TelemetryModel.supplier_id == TARGET_SUPPLIER
        ).order_by(TelemetryModel.recorded_at.asc()).all()
        
        inventory_data = [r.inventory_count for r in records if r.inventory_count is not None]
        print(f"Loaded {len(inventory_data)} records for {TARGET_SUPPLIER}")
        
        if len(inventory_data) < (CONTEXT_LENGTH + PREDICTION_LENGTH + NUM_BACKTEST_WINDOWS):
            print("❌ Insufficient data for backtesting. Run generation script first.")
            return

        # 2. Load the bare Chronos Pipeline (Bypassing the API gateway)
        print("⏳ Loading Chronos-T5-Mini into memory...")
        pipeline = ChronosPipeline.from_pretrained(
            "amazon/chronos-t5-mini",
            device_map="cpu",
            torch_dtype=torch.float32,
        )

        metrics = {"latencies": [], "mape_scores": [], "mae_scores": []}

        print(f"🚀 Running {NUM_BACKTEST_WINDOWS} historical sliding windows...")
        
        # 3. The Sliding Window Backtest
        # We start from the end of the dataset and walk backward
        start_idx = len(inventory_data) - PREDICTION_LENGTH - NUM_BACKTEST_WINDOWS
        
        for i in range(NUM_BACKTEST_WINDOWS):
            window_end = start_idx + i
            window_start = window_end - CONTEXT_LENGTH
            
            # The data the model is allowed to "see" (shape [1, 90])
            context_tensor = torch.tensor(inventory_data[window_start:window_end], dtype=torch.float32).view(1, -1)
            
            # The actual future data we are hiding from the model
            ground_truth = inventory_data[window_end : window_end + PREDICTION_LENGTH]
            
            # Run Inference
            start_time = time.time()
            forecast = pipeline.predict(
                context_tensor,
                prediction_length=PREDICTION_LENGTH,
                num_samples=20
            )
            inference_time = time.time() - start_time
            
            # Extract the median (50th percentile) prediction
            # check type of forecast to handle numpy arrays vs torch tensors
            if isinstance(forecast[0], torch.Tensor):
                forecast_array = forecast[0].numpy()
            else:
                forecast_array = forecast[0]
                
            median_forecast = np.quantile(forecast_array, 0.5, axis=0)
            
            # Calculate Errors
            mape = calculate_mape(ground_truth, median_forecast)
            mae = calculate_mae(ground_truth, median_forecast)
            
            metrics["latencies"].append(inference_time)
            metrics["mape_scores"].append(mape)
            metrics["mae_scores"].append(mae)
            
            print(f"Window {i+1}: MAPE={mape:.2f}% | MAE={mae:.2f} units | Latency={inference_time:.3f}s")

        # 4. Generate Final Evaluation Report
        avg_mape = np.mean(metrics["mape_scores"])
        avg_mae = np.mean(metrics["mae_scores"])
        avg_latency = np.mean(metrics["latencies"])
        
        print("\n📊 --- CHRONOS-T5 MODEL ACCURACY REPORT ---")
        print(f"Average MAPE (Error %): {avg_mape:.2f}%")
        print(f"Average MAE (Unit Miss): {avg_mae:.2f} units")
        print(f"Average CPU Latency: {avg_latency:.3f} sec/inference")
        
        report = {
            "phase": "EVAL_PHASE_5_ML_BACKTEST",
            "status": "COMPLETED",
            "supplier_tested": TARGET_SUPPLIER,
            "data_points_analyzed": len(inventory_data),
            "avg_mape_percent": round(avg_mape, 2),
            "avg_mae_units": round(avg_mae, 2),
            "avg_inference_latency_sec": round(avg_latency, 3)
        }
        with open("ml_accuracy_report.json", "w") as f:
            json.dump(report, f, indent=2)

    except Exception as e:
        print(f"❌ Execution Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    run_backtest()
