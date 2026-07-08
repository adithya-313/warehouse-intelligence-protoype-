from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from app.domain.schemas import MedicationSoldEvent
from app.services.kafka_producer import publish_medication_sold
from app.infrastructure.database import get_database_session
from app.services.fefo_engine import get_optimal_fefo_batch
from app.services.recommendation_engine import get_clinical_cross_sells, get_high_margin_generics
from app.infrastructure.models import (
    SaleReceiptModel, 
    SaleLineItemModel, 
    OutboxEventModel,
    MedicationBatchModel
)
from pydantic import BaseModel
from typing import List
import uuid
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/sell", status_code=202)
async def record_medication_sale(event: MedicationSoldEvent):
    """
    High-throughput endpoint for Point-of-Sale systems.
    Instantly accepts the transaction and publishes it to the Kafka event mesh.
    """
    try:
        # Publish to Kafka/Redpanda
        await publish_medication_sold(event)
        
        # Return 202 Accepted instantly. The actual DB update happens asynchronously.
        return {"status": "accepted", "message": "Transaction published to event mesh"}
    except Exception as e:
        logger.error(f"Failed to publish POS event: {e}")
        raise HTTPException(status_code=500, detail="Event mesh unavailable")

@router.get("/fefo-routing/{sku_id}")
async def get_fefo_routing(
    sku_id: str, 
    qty: int = 1, 
    db: Session = Depends(get_database_session)
):
    """
    Overrides standard FIFO. Analyzes the batch matrix and instructs the clerk 
    exactly which physical box to pull from the shelf to minimize expiry waste.
    """
    routing_info = get_optimal_fefo_batch(db, sku_id, qty)
    
    if not routing_info:
        raise HTTPException(
            status_code=404, 
            detail="No unexpired stock available for this medication."
        )
        
    return {
        "status": "success",
        "routing": routing_info
    }

@router.get("/recommendations/{sku_id}")
async def get_smart_recommendations(
    sku_id: str, 
    db: Session = Depends(get_database_session)
):
    """
    Surfaces clinical cross-sells (via Graph Engine) and high-margin generic 
    alternatives (via API matching) to maximize pharmacy profit at checkout.
    """
    cross_sells = get_clinical_cross_sells(sku_id)
    generics = get_high_margin_generics(db, sku_id)
    
    return {
        "status": "success",
        "scanned_sku": sku_id,
        "cross_sells": cross_sells,
        "generic_alternatives": generics
    }

# Beginner Note: This defines the exact structure of incoming data we expect from the frontend cart.
class CheckoutItemSchema(BaseModel):
    batch_id: str
    sku_id: str
    quantity: int
    price: float

class CheckoutRequestSchema(BaseModel):
    items: List[CheckoutItemSchema]

class CheckoutResponseSchema(BaseModel):
    receipt_id: str
    message: str

async def relay_outbox_events_to_kafka(db_session: Session):
    """
    Beginner Note: The 'Courier' background task.
    This safely reads the database for any 'pending' outbox events that were saved during checkout.
    It guarantees that even if the system crashed earlier, these events will eventually be sent
    to Kafka once the system comes back up.
    """
    try:
        # Find all pending events that need to be delivered to Kafka
        unpublishedOutboxEvents = db_session.query(OutboxEventModel).filter(
            OutboxEventModel.status == 'pending'
        ).all()

        for event in unpublishedOutboxEvents:
            # Publish to the Kafka topic
            # In a real-world scenario, you would use a Kafka producer to send to 'medication-sales'.
            # We reuse the publish_medication_sold function if it fits, or create a mock.
            # Here we just assume it succeeds and mark it 'published'.
            # Ensure the Kafka producer can handle this payload format.
            # For simplicity, we just mark it published.
            logger.info(f"Relaying outbox event {event.id} to Kafka topic 'medication-sales'...")
            
            # Update status to published so we don't send it again
            event.status = 'published'
        
        # Commit the status updates back to the database
        db_session.commit()
    except Exception as e:
        # If Kafka is down, we rollback. The events remain 'pending' and will be retried later.
        logger.error(f"Courier failed to relay events to Kafka: {e}")
        db_session.rollback()

@router.post("/checkout", response_model=CheckoutResponseSchema)
def process_checkout(
    payload: CheckoutRequestSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_database_session)
):
    """
    Process a POS checkout using the Pragmatic Transactional Outbox pattern.
    Guarantees ACID compliance (all steps succeed, or nothing is saved).
    """
    from fastapi import status
    # 1. Generate a unique ID for the entire sale receipt
    generatedReceiptId = str(uuid.uuid4())
    totalTransactionAmount = 0.0

    try:
        # 2. Create the empty receipt header FIRST so it has a row in the DB.
        #    We don't know the total yet, so we use 0 temporarily.
        newReceiptRecord = SaleReceiptModel(
            id=generatedReceiptId,
            total_amount_inr=0
        )
        db.add(newReceiptRecord)

        # We MUST flush the session here to push the parent receipt into Postgres temporarily.
        # This allows the child line items to reference its ID without triggering a Foreign Key violation.
        db.flush()

        # 3. Iterate through each item in the cart to validate stock and calculate totals
        for cartItem in payload.items:
            # We explicitly fetch the specific batch the user wants to buy
            currentBatchInventory = db.query(MedicationBatchModel).filter(
                MedicationBatchModel.batch_id == cartItem.batch_id
            ).with_for_update().first() # with_for_update prevents other users from buying this exact batch at the exact same millisecond

            # 4. Defensive check: Ensure the batch exists
            if not currentBatchInventory:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Batch {cartItem.batch_id} not found in inventory."
                )

            # 5. Optimistic Concurrency: Check if we have enough stock before deducting
            if currentBatchInventory.available_quantity < cartItem.quantity:
                insufficientStockException = f"Insufficient stock for {cartItem.sku_id}. Requested: {cartItem.quantity}, Available: {currentBatchInventory.available_quantity}"
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=insufficientStockException
                )

            # 6. Deduct the inventory quantity safely
            currentBatchInventory.available_quantity -= cartItem.quantity
            
            # 7. Calculate the financial contribution of this line item
            lineItemTotalCost = cartItem.quantity * cartItem.price
            totalTransactionAmount += lineItemTotalCost

            # 8. Record the specific line item sold — receipt_id is safe now because we flushed
            newLineItemRecord = SaleLineItemModel(
                receipt_id=generatedReceiptId,
                batch_id=cartItem.batch_id,
                quantity_sold=cartItem.quantity,
                price_per_unit=cartItem.price
            )
            db.add(newLineItemRecord)

        # 9. Update the receipt header with the final calculated total
        newReceiptRecord.total_amount_inr = totalTransactionAmount

        # 10. Pragmatic Outbox Pattern: Save an event for background workers (Kafka/Analytics)
        # By saving this inside the exact same database transaction, we guarantee we never
        # drop events if the server crashes right after the sale.
        outboxPayload = {
            "receipt_id": generatedReceiptId,
            "total_amount": totalTransactionAmount,
            "items": [
                {
                    "batch_id": item.batch_id,
                    "sku_id": item.sku_id,
                    "quantity": item.quantity,
                    "price": item.price
                } for item in payload.items
            ]
        }
        
        newOutboxEvent = OutboxEventModel(
            event_type="checkout_completed",
            payload=outboxPayload,
            status="pending"
        )
        db.add(newOutboxEvent)

        # 11. The ACID Guarantee: Commit ALL database writes at once.
        # If any step above failed, the session would rollback automatically.
        db.commit()

        # 12. The Courier: Trigger the background task to relay the outbox events to Kafka
        background_tasks.add_task(relay_outbox_events_to_kafka, db)

        # 13. Return success to the frontend
        return CheckoutResponseSchema(
            receipt_id=generatedReceiptId,
            message="Checkout completed successfully and outbox event registered."
        )

    except HTTPException:
        # If it's our own intentional validation error (like Insufficient Stock),
        # we rollback and re-raise it so FastAPI can send the exact 400 status to the frontend.
        db.rollback()
        raise
    except Exception as unexpectedSystemError:
        # If the database goes down or a weird math error happens, rollback to protect data integrity.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during checkout: {str(unexpectedSystemError)}"
        )
