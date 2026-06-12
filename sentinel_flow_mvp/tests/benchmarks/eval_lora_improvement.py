import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import torch
import time
import numpy as np
import json
import hashlib
from peft import LoraConfig, TaskType, get_peft_model
from transformers import AutoModelForSeq2SeqLM
from app.infrastructure.database import SessionLocal
from app.infrastructure.models import TelemetryModel
from app.infrastructure.db.models import LoRAAdapterRegistry
from chronos import ChronosPipeline

# --- CONFIGURATION ---
BASE_URL = "http://localhost:8080/api/v1"
TARGET_SUPPLIER = "NVIDIA"
CONTEXT_LENGTH = 90
PREDICTION_LENGTH = 5
NUM_BACKTEST_WINDOWS = 10
BASELINE_MAPE = 19.32  # Extracted from Eval Phase 5

def calculate_mape(actual, predicted):
    actual, predicted = np.array(actual), np.array(predicted)
    mask = actual != 0
    if not mask.any(): return 0.0
    return np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])) * 100

def generate_file_hash(filepath: str) -> str:
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def create_time_series_tensors(data_array, window_size=30, forecast_horizon=5):
    min_val = np.min(data_array)
    max_val = np.max(data_array)
    if max_val - min_val > 0:
        scaled_data = (data_array - min_val) / (max_val - min_val)
    else:
        scaled_data = np.zeros_like(data_array)
    X, y = [], []
    for i in range(len(scaled_data) - window_size - forecast_horizon + 1):
        X.append(scaled_data[i : i + window_size])
        y.append(scaled_data[i + window_size : i + window_size + forecast_horizon])
    return torch.tensor(X, dtype=torch.float32), torch.tensor(y, dtype=torch.float32)

def train_and_register_lora():
    print("🚀 Running CPU training loop to generate a real LoRA adapter...")
    db = SessionLocal()
    try:
        # 1. Fetch telemetry data
        records = db.query(TelemetryModel).filter(
            TelemetryModel.supplier_id == TARGET_SUPPLIER
        ).order_by(TelemetryModel.recorded_at.asc()).all()
        
        inventory_data = np.array([r.inventory_count for r in records], dtype=float)
        print(f"Loaded {len(inventory_data)} records for training.")
        
        # 2. Window time series data
        x_train, y_train = create_time_series_tensors(inventory_data, window_size=30, forecast_horizon=5)
        
        # 3. Load base model and wrap with LoRA config
        print("Loading base T5 model on CPU...")
        base_model = AutoModelForSeq2SeqLM.from_pretrained(
            "amazon/chronos-t5-mini",
            torch_dtype=torch.float32,
        )
        
        lora_config = LoraConfig(
            r=8,
            lora_alpha=16,
            target_modules=["q", "v"],
            lora_dropout=0.1,
            bias="none",
            task_type=TaskType.SEQ_2_SEQ_LM,
        )
        peft_model = get_peft_model(base_model, lora_config)
        
        # 4. Train brief 1 epoch
        optimiser = torch.optim.AdamW(peft_model.parameters(), lr=1e-3)
        loss_fn = torch.nn.MSELoss()
        peft_model.train()
        
        batch_size = 4
        num_samples = len(x_train)
        num_batches = max(1, num_samples // batch_size)
        
        print(f"Training 1 epoch on CPU ({num_batches} batches)...")
        for batch_idx in range(num_batches):
            start = batch_idx * batch_size
            end = start + batch_size
            batch_x = x_train[start:end]
            batch_y = y_train[start:end]
            
            outputs = peft_model(
                input_ids=batch_x.long(),
                decoder_input_ids=batch_y.long()
            )
            preds = outputs.logits.mean(dim=-1)
            loss = loss_fn(preds, batch_y)
            
            loss.backward()
            optimiser.step()
            optimiser.zero_grad()
            
            if (batch_idx + 1) % 100 == 0:
                print(f"Batch {batch_idx + 1}/{num_batches} | Loss: {loss.item():.4f}")
                
        # 5. Save model to disk
        adapter_dir = "/app/lora_adapters/NVIDIA"
        os.makedirs(adapter_dir, exist_ok=True)
        peft_model.save_pretrained(adapter_dir)
        print(f"Adapter model saved to {adapter_dir}")
        
        # Compute checksum
        safetensors_path = os.path.join(adapter_dir, "adapter_model.safetensors")
        checksum = generate_file_hash(safetensors_path)
        print(f"Generated checksum: {checksum}")
        
        # 6. Register adapter in DB
        adapter_id = "nvidia_lora_adapter"
        existing = db.query(LoRAAdapterRegistry).filter_by(id=adapter_id).first()
        if existing:
            existing.adapter_weights_path = adapter_dir
            existing.checksum = checksum
            existing.status = "ACTIVE"
        else:
            new_adapter = LoRAAdapterRegistry(
                id=adapter_id,
                module_name="demand_forecast",
                supplier_id=TARGET_SUPPLIER,
                base_model_version="chronos_base_v1",
                adapter_weights_path=adapter_dir,
                checksum=checksum,
                status="ACTIVE",
            )
            db.add(new_adapter)
        db.commit()
        print("Adapter successfully registered as ACTIVE in database.")
        return adapter_dir
    except Exception as e:
        print(f"❌ Failed in training/registration: {e}")
        db.rollback()
        raise
    finally:
        db.close()

def run_adapted_backtest(adapter_path: str):
    print(f"🧠 INITIATING ML BACKTESTING WITH LORA ADAPTER: {adapter_path}...")
    db = SessionLocal()
    
    try:
        records = db.query(TelemetryModel).filter(
            TelemetryModel.supplier_id == TARGET_SUPPLIER
        ).order_by(TelemetryModel.recorded_at.asc()).all()
        
        inventory_data = [r.inventory_count for r in records if r.inventory_count is not None]

        print("⏳ Loading Chronos-T5-Mini + LoRA Weights into memory...")
        pipeline = ChronosPipeline.from_pretrained(
            "amazon/chronos-t5-mini",
            device_map="cpu",
            torch_dtype=torch.float32,
        )
        
        # Inject the custom LoRA weights to the inner model
        pipeline.model.model.load_adapter(adapter_path)
        
        metrics = {"mape_scores": []}
        start_idx = len(inventory_data) - PREDICTION_LENGTH - NUM_BACKTEST_WINDOWS
        
        for i in range(NUM_BACKTEST_WINDOWS):
            window_end = start_idx + i
            window_start = window_end - CONTEXT_LENGTH
            
            context_tensor = torch.tensor(inventory_data[window_start:window_end], dtype=torch.float32).view(1, -1)
            ground_truth = inventory_data[window_end : window_end + PREDICTION_LENGTH]
            
            forecast = pipeline.predict(
                context_tensor,
                prediction_length=PREDICTION_LENGTH,
                num_samples=20
            )
            
            if isinstance(forecast[0], torch.Tensor):
                forecast_array = forecast[0].numpy()
            else:
                forecast_array = forecast[0]
                
            median_forecast = np.quantile(forecast_array, 0.5, axis=0)
            mape = calculate_mape(ground_truth, median_forecast)
            metrics["mape_scores"].append(mape)
            
            print(f"Window {i+1}: MAPE={mape:.2f}%")

        tuned_mape = np.mean(metrics["mape_scores"])
        improvement = BASELINE_MAPE - tuned_mape
        
        print("\n📊 --- LORA FINE-TUNING ACCURACY DELTA ---")
        print(f"Baseline MAPE (Zero-Shot) : {BASELINE_MAPE:.2f}%")
        print(f"Tuned MAPE (LoRA Adapter): {tuned_mape:.2f}%")
        print(f"Net Accuracy Improvement  : +{improvement:.2f}%")
        
        report = {
            "phase": "EVAL_PHASE_6_LORA_IMPROVEMENT",
            "status": "COMPLETED",
            "baseline_mape": BASELINE_MAPE,
            "tuned_mape": round(tuned_mape, 2),
            "improvement_points": round(improvement, 2)
        }
        with open("lora_accuracy_report.json", "w") as f:
            json.dump(report, f, indent=2)

    except Exception as e:
        print(f"❌ Execution Error: {e}")
        raise
    finally:
        db.close()

def main():
    # Execute training and save adapter
    adapter_path = train_and_register_lora()
    if adapter_path:
        # Run adapted backtest
        run_adapted_backtest(adapter_path)

if __name__ == "__main__":
    main()
