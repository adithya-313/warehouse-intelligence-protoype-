import os
from app.infrastructure.database import SessionLocal
from sqlalchemy import text

def promote():
    db = SessionLocal()
    db.execute(text("UPDATE lora_adapter_registry SET status='ACTIVE' WHERE module_name='demand_forecast'"))
    db.commit()
    print("Promoted adapter to ACTIVE")
    
    path = "lora_adapters/92df9862-156d-4878-b578-0a92f8ff903e.bin"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write("mock weights")
    print("Created mock file")
    
    db.close()

if __name__ == "__main__":
    promote()
