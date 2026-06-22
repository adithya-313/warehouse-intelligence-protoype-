import asyncio
import json
import logging
from aiokafka import AIOKafkaConsumer
from sqlalchemy.orm import Session
from app.infrastructure.database import SessionLocal
from app.infrastructure.models import MedicationBatchModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def consume_sales_events():
    """
    Background worker that listens to Kafka and updates the TimescaleDB ledger.
    Beginner Note: This runs independently of the API. It pulls events from the 
    'medication-sales' topic and safely deducts inventory.
    """
    consumer = AIOKafkaConsumer(
        'medication-sales',
        bootstrap_servers='localhost:9092',
        group_id="ledger-updater-group",
        value_deserializer=lambda m: json.loads(m.decode('utf-8'))
    )
    
    await consumer.start()
    logger.info("Kafka Consumer started. Listening for POS events...")
    
    try:
        async for msg in consumer:
            event_data = msg.value
            batch_id = event_data.get("batch_id")
            qty_sold = event_data.get("quantity_sold", 0)
            
            # Open a database session to update the ledger
            db: Session = SessionLocal()
            try:
                # 1. Fetch the batch and LOCK the row until this transaction completes.
                # Beginner Note: .with_for_update() translates to 'SELECT ... FOR UPDATE' in SQL.
                # If Cashier A and Cashier B scan the exact same batch at the exact same millisecond,
                # the database forces Cashier B to wait in line until Cashier A finishes.
                batch = db.query(MedicationBatchModel).filter(
                    MedicationBatchModel.batch_id == batch_id
                ).with_for_update().first()
                
                if batch:
                    # 2. Strict validation: Do we actually have enough stock?
                    # This prevents "ghost stock" (negative inventory) if two cashiers 
                    # try to sell the last remaining box.
                    if batch.available_quantity >= qty_sold:
                        batch.available_quantity -= qty_sold
                        db.commit() # This saves the change AND releases the row lock
                        logger.info(f"Ledger updated: Batch {batch_id} reduced by {qty_sold}. Remaining: {batch.available_quantity}")
                    else:
                        # We don't have enough stock! Reject the transaction.
                        db.rollback() # Release the lock without making changes
                        logger.warning(f"Ghost stock prevented! Batch {batch_id} only has {batch.available_quantity} units. Cannot sell {qty_sold}.")
                else:
                    logger.warning(f"Batch {batch_id} not found in ledger. Event ignored.")
            except Exception as e:
                db.rollback() # Always release the lock if something crashes
                logger.error(f"Database error updating ledger: {e}")
            finally:
                db.close()
                
    finally:
        await consumer.stop()

if __name__ == "__main__":
    # To run this worker: python -m app.workers.kafka_consumer
    asyncio.run(consume_sales_events())
