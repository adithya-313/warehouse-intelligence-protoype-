import asyncio
import traceback
import torch
import sys
from chronos import ChronosPipeline
from app.infrastructure.database import SessionLocal
from app.infrastructure.models import TelemetryModel
from app.infrastructure.db.models import LoRAAdapterRegistry

async def debug_chronos():
    print("=== STARTING ML DIAGNOSTIC ===")
    
    sku_id = "SKU-NV-5090"
    supplier_id = "NVIDIA Corporation"
    
    db_session = SessionLocal()
    try:
        print(f"Fetching telemetry for {sku_id}...")
        records = db_session.query(TelemetryModel).filter(
            TelemetryModel.supplier_id == supplier_id,
            TelemetryModel.sku_id == sku_id
        ).order_by(TelemetryModel.recorded_at.desc()).limit(90).all()
        
        if not records:
            print(f"No records found for {sku_id}")
            return
            
        records.reverse()
        inventory_data = [float(r.inventory_count) for r in records]
        
        print(f"Length of fetched data: {len(inventory_data)}")
        print(f"Data type of fetched data: {type(inventory_data[0])}")
        
        if len(inventory_data) < 90:
            padding = [inventory_data[0]] * (90 - len(inventory_data))
            inventory_data = padding + inventory_data
        elif len(inventory_data) > 90:
            inventory_data = inventory_data[-90:]
            
        # Checkpoint 1
        print(f"[Checkpoint 1] Shape of historical array before tensor conversion: {len(inventory_data)}")
        
        # Checkpoint 2
        try:
            context_tensor = torch.tensor(inventory_data, dtype=torch.float32).view(1, 90)
            print(f"[Checkpoint 2] Shape: {context_tensor.shape}, Device: {context_tensor.device}, Dtype: {context_tensor.dtype}")
        except Exception as e:
            print(f"[Checkpoint 2 ERROR] Tensor conversion failed: {e}")
            traceback.print_exc()
            return
            
        # Checkpoint 3
        adapter_record = db_session.query(LoRAAdapterRegistry).filter(
            LoRAAdapterRegistry.module_name == "demand_forecast",
            LoRAAdapterRegistry.supplier_id == supplier_id,
            LoRAAdapterRegistry.status == "ACTIVE"
        ).order_by(LoRAAdapterRegistry.created_at.desc()).first()
        
        if adapter_record:
            print(f"[Checkpoint 3] Found adapter path: {adapter_record.adapter_weights_path}")
            import os
            print(f"[Checkpoint 3] Does adapter file exist? {os.path.exists(adapter_record.adapter_weights_path)}")
        else:
            print("[Checkpoint 3] No active LoRA adapter found, falling back to chronos_base_v1")
            
        # Checkpoint 4
        print(f"[Checkpoint 4] Initializing ChronosPipeline and executing prediction...")
        try:
            pipeline = ChronosPipeline.from_pretrained(
                "amazon/chronos-t5-mini",
                device_map="cuda" if torch.cuda.is_available() else "cpu",
                torch_dtype=torch.float32
            )
            print(f"ChronosPipeline loaded successfully on device: {pipeline.model.device}")
            
            if adapter_record and adapter_record.adapter_weights_path:
                import os
                if not os.path.exists(adapter_record.adapter_weights_path):
                    print(f"Adapter path does not exist: {adapter_record.adapter_weights_path}. Skipping adapter.")
                else:
                    try:
                        print(f"Loading adapter from {adapter_record.adapter_weights_path}")
                        pipeline.model.load_adapter(adapter_record.adapter_weights_path, adapter_name="current_lora")
                        pipeline.model.set_adapter("current_lora")
                    except Exception as e:
                        print(f"Failed to load LoRA adapter. Falling back to base model. Error: {e}")
            
            print("Executing pipeline.predict()...")
            forecast = pipeline.predict(context_tensor, prediction_length=5)
            
            predicted_demand = float(forecast[0].median().item() if hasattr(forecast[0], 'median') else forecast[0].mean().item())
            print(f"Prediction successful! Value: {predicted_demand}")
            
        except Exception as e:
            print(f"[Checkpoint 4 ERROR] Prediction step failed:")
            print(f"Exception Type: {type(e).__name__}")
            print(f"Exception Message: {str(e)}")
            traceback.print_exc()

    finally:
        db_session.close()

if __name__ == "__main__":
    asyncio.run(debug_chronos())
