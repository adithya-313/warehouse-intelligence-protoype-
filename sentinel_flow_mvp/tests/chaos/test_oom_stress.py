import sys
import os

# Add the project root to sys.path so we can import from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.services.lora_training_worker import train_lora_adapter
import time

def run_stress_test():
    print("OOM Stress Test: Queueing 5 simultaneous LoRA training tasks...")
    task_ids = []
    for i in range(5):
        supplier_id = f"stress_test_supplier_{i}"
        print(f"Queueing training for {supplier_id}")
        # Note: train_lora_adapter is a Celery task. If Celery is not running, 
        # this will just queue them in Redis/RabbitMQ.
        # We use .apply_async() or .delay() to queue it.
        result = train_lora_adapter.delay(
            module_name="demand_forecast", 
            supplier_id=supplier_id
        )
        task_ids.append(result.id)
        
    print(f"Successfully queued 5 tasks. Task IDs: {task_ids}")
    print("You can monitor the celery worker logs to verify OOM survival.")

if __name__ == "__main__":
    run_stress_test()
