from app.infrastructure.database import SessionLocal
from app.infrastructure.db.models import LoRAAdapterRegistry
from datetime import datetime, timezone, timedelta

def seed_mlops_registry():
    db = SessionLocal()
    try:
        db.query(LoRAAdapterRegistry).delete()

        now = datetime.now(timezone.utc)

        adapters = [
            # NVIDIA - Mature pipeline with active and archived models
            LoRAAdapterRegistry(
                id="lora_nv_v3_prod", module_name="demand_forecast", supplier_id="NVIDIA",
                base_model_version="amazon/chronos-t5-mini", adapter_weights_path="/app/ml/weights/nv_demand_v3.safetensors",
                checksum="e3b0c44298fc1c149afbf4c8996fb924", status="ACTIVE", created_at=now - timedelta(days=1)
            ),
            LoRAAdapterRegistry(
                id="lora_nv_v2_old", module_name="demand_forecast", supplier_id="NVIDIA",
                base_model_version="amazon/chronos-t5-mini", adapter_weights_path="/app/ml/weights/nv_demand_v2.safetensors",
                checksum="8f434346648f6b96df89dda901c5176b", status="ARCHIVED", created_at=now - timedelta(days=15)
            ),
            # Intel - Currently training a new adapter due to drift
            LoRAAdapterRegistry(
                id="lora_in_v2_train", module_name="demand_forecast", supplier_id="Intel",
                base_model_version="amazon/chronos-t5-mini", adapter_weights_path="s3://ml-artifacts/intel/training_v2.tmp",
                checksum="PENDING", status="TRAINING", created_at=now
            ),
            LoRAAdapterRegistry(
                id="lora_in_v1_prod", module_name="demand_forecast", supplier_id="Intel",
                base_model_version="amazon/chronos-t5-mini", adapter_weights_path="/app/ml/weights/in_demand_v1.safetensors",
                checksum="d41d8cd98f00b204e9800998ecf8427e", status="ACTIVE", created_at=now - timedelta(days=30)
            ),
            # AMD - Failed validation, rolled back
            LoRAAdapterRegistry(
                id="lora_amd_v2_fail", module_name="demand_forecast", supplier_id="AMD",
                base_model_version="amazon/chronos-t5-mini", adapter_weights_path="/app/ml/quarantine/amd_demand_v2_corrupted.safetensors",
                checksum="CORRUPTED_HASH_MISMATCH", status="FAILED_VALIDATION", created_at=now - timedelta(days=2)
            ),
            LoRAAdapterRegistry(
                id="lora_amd_v1_prod", module_name="demand_forecast", supplier_id="AMD",
                base_model_version="amazon/chronos-t5-mini", adapter_weights_path="/app/ml/weights/amd_demand_v1.safetensors",
                checksum="c4ca4238a0b923820dcc509a6f75849b", status="ACTIVE", created_at=now - timedelta(days=45)
            )
        ]

        db.add_all(adapters)
        db.commit()
        print("MLOps Registry successfully hydrated with realistic adapter history.")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_mlops_registry()
