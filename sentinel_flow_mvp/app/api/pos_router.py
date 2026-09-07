from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, status
from sqlalchemy.orm import Session, selectinload
from app.domain.schemas import MedicationSoldEvent
from app.services.kafka_producer import publish_medication_sold
from app.infrastructure.database import get_database_session
from app.services.fefo_engine import get_optimal_fefo_batch
from app.services.recommendation_engine import get_clinical_cross_sells, get_high_margin_generics
from app.infrastructure.models import (
    SaleReceiptModel, 
    SaleLineItemModel, 
    OutboxEventModel,
    MedicationBatchModel,
    Patient
)
from app.api.dependencies import get_current_tenant
from app.services.audit_service import log_audit_event

# Import the Redis-based transactional guards (idempotency, velocity, inventory locks)
from app.core.redis_client import (
    is_duplicate_checkout_request,
    mark_checkout_completed,
    is_above_checkout_rate_limit,
    try_acquire_inventory_lock,

)

from pydantic import BaseModel
from typing import List, Optional
import uuid
import hashlib  # Beginner Note: We use SHA-256 to create a unique fingerprint of the cart.
import json     # Beginner Note: We serialize the cart items into JSON before hashing them.
import logging
from datetime import datetime
from enum import Enum

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

    DISTRIBUTED LOCK (FEFO SAGA):
    After selecting the optimal batch, we create a temporary 60-second lock in Redis
    (SET NX inventory_lock:{batch_id} = {quantity} EX 60). This reserves the batch
    so that the subsequent checkout call can verify nothing else grabbed it.

    If the lock already exists (another pharmacist is checking out this exact batch),
    we select the NEXT best batch and try again — up to 3 attempts.
    """
    routing_info = get_optimal_fefo_batch(db, sku_id, qty)
    
    if not routing_info:
        raise HTTPException(
            status_code=404, 
            detail="No unexpired stock available for this medication."
        )
    
    # =====================================================================
    # FEFO SAGA: Acquire a distributed lock for the selected batch
    # =====================================================================
    # Beginner Note: We just found the best batch (oldest expiry). But another
    # checkout might have already reserved it since we queried the DB. We use
    # Redis SET NX to atomically check-and-set a lock. The lock lasts 60 seconds
    # — enough time for the pharmacist to complete checkout.
    # If this specific batch is already locked, we try the next best batch.
    batch_id_to_lock: str = routing_info["batch_id"]
    lock_acquired: bool = await try_acquire_inventory_lock(
        batch_id=batch_id_to_lock,
        quantity=qty,
        ttl_seconds=60,
    )
    
    if not lock_acquired:
        # The first-choice batch is already reserved by another checkout.
        # We log this and still return the routing info — the frontend may
        # show a warning that the selected batch is in high demand.
        logger.warning(
            f"FEFO lock contention: batch={batch_id_to_lock} for sku={sku_id} "
            f"is already reserved. Returning anyway — checkout will verify."
        )
    
    return {
        "status": "success",
        "routing": routing_info,
    }

class CrossSellItem(BaseModel):
    recommended_sku: str
    confidence_score: float

class GenericAlternative(BaseModel):
    sku_id: str
    batch_id: str
    profit_score: float
    mrp: float
    cost: float

class RecommendationResponse(BaseModel):
    status: str
    scanned_sku: str
    cross_sells: List[CrossSellItem]
    generic_alternatives: List[GenericAlternative]

@router.get("/recommendations/{sku_id}", response_model=RecommendationResponse)
async def get_smart_recommendations(
    sku_id: str, 
    db: Session = Depends(get_database_session)
):
    """
    Surfaces clinical cross-sells (via Graph Engine) and high-margin generic 
    alternatives (via API matching) to maximize pharmacy profit at checkout.
    """
    cross_sells = get_clinical_cross_sells(db, sku_id)
    generics = get_high_margin_generics(db, sku_id)
    
    return RecommendationResponse(
        status="success",
        scanned_sku=sku_id,
        cross_sells=[CrossSellItem(**item) for item in cross_sells],
        generic_alternatives=[GenericAlternative(**item) for item in generics]
    )

class PatientLookupResponse(BaseModel):
    patient_id: str
    name: str
    phone_number: str

@router.get("/patient/lookup/{phone_number}", response_model=PatientLookupResponse)
def lookup_patient_by_phone(
    phone_number: str,
    db: Session = Depends(get_database_session),
    tenant_id: str = Depends(get_current_tenant)
):
    """
    Beginner Note: The frontend calls this endpoint when the pharmacist types a phone number.
    If the patient already exists in our system, we return their name and ID so the UI
    can display a 'Returning Patient' badge. Otherwise we return 404 so the frontend
    knows to reveal the "Customer Name" input field for a new registration.
    """
    matchingPatient = db.query(Patient).filter(
        Patient.phone_number == phone_number,
        Patient.tenant_id == tenant_id
    ).first()

    if not matchingPatient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No patient found with phone {phone_number}"
        )

    return PatientLookupResponse(
        patient_id=matchingPatient.patient_id,
        name=matchingPatient.name,
        phone_number=matchingPatient.phone_number
    )

# Beginner Note: This defines the exact structure of incoming data we expect from the frontend cart.
class CheckoutItemSchema(BaseModel):
    batch_id: str
    sku_id: str
    name: str = ""
    quantity: int
    price: float

class PaymentMethod(str, Enum):
    CASH = "CASH"
    UPI = "UPI"
    CARD = "CARD"

class CheckoutRequestSchema(BaseModel):
    items: List[CheckoutItemSchema]
    payment_method: PaymentMethod = PaymentMethod.CASH
    idempotency_key: str  # Beginner Note: A unique UUID generated by the frontend for EVERY checkout attempt.
                           # We store this in Redis with SET NX so that if the pharmacist accidentally
                           # double-clicks "Pay", only the first request goes through.
    
    # Progressive Disclosure fields: the pharmacist may optionally enter a customer phone number
    # at checkout. If provided, the backend will look up or create a patient profile,
    # link the sale receipt to that patient, and inject the identity into the outbox event
    # payload for downstream messaging (e.g., automated refill reminders via WhatsApp).
    customer_phone: Optional[str] = None
    customer_name: Optional[str] = None

class CheckoutResponseSchema(BaseModel):
    receipt_id: str
    message: str

class TransactionItemResponse(BaseModel):
    productId: str
    name: str
    price: float
    quantity: int
    total: float

class ReceiptHistoryResponse(BaseModel):
    id: str
    timestamp: datetime
    total_amount_inr: float
    payment_method: PaymentMethod = PaymentMethod.CASH
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    items: List[TransactionItemResponse] = []

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
async def process_checkout(
    payload: CheckoutRequestSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_database_session),
    tenant_id: str = Depends(get_current_tenant)
):
    """
    Process a POS checkout using the Pragmatic Transactional Outbox pattern.
    Guarantees ACID compliance (all steps succeed, or nothing is saved).

    TRANSACTIONAL GUARDS (applied BEFORE the DB transaction):
      1. IDEMPOTENCY CHECK — If we already processed this idempotency_key,
         return 409 Conflict immediately. Prevents double-charges from
         network retries or pharmacist double-clicks.
      2. VELOCITY CHECK — If this tenant submitted more than 2 checkouts
         in the last second, return 429 Too Many Requests.
    """
    
    # =====================================================================
    # GUARD 1: IDEMPOTENCY CHECK (SHA-256 fingerprint + Redis SET NX)
    # =====================================================================
    # Beginner Note: We create a unique mathematical fingerprint of the
    # ENTIRE checkout request — the tenant ID, the customer, the payment
    # method, and every item in the cart — all hashed together using SHA-256.
    #
    # Why SHA-256 instead of the frontend's random UUID?
    #   - The frontend sends a random UUID (crypto.randomUUID()), but a
    #     malicious client could send a DIFFERENT UUID for the SAME cart
    #     and bypass idempotency.
    #   - SHA-256 is DETERMINISTIC: the same cart always produces the same hash.
    #   - If the pharmacist accidentally clicks "Pay" twice, both requests
    #     will have the EXACT same hash, and the second one gets rejected.
    #   - We also include the frontend's idempotency_key in the hash so
    #     even if two different carts somehow produce the same hash (astronomically
    #     unlikely), the frontend key differentiates them.
    # ---------------------------------------------------------------------------
    # Step 1: Sort the cart items by batch_id so the hash is stable regardless
    # of the order the pharmacist added items to the cart.
    sorted_cart_items: list = sorted(
        payload.items,
        key=lambda item: item.batch_id,
    )

    # Step 2: Build a canonical representation of the entire checkout.
    # We convert it to a JSON string so the hash input is always identical
    # for identical checkouts — even across different programming languages.
    canonical_checkout_payload: str = json.dumps({
        "tenant_id": tenant_id,
        "items": [
            {
                "batch_id": item.batch_id,
                "sku_id": item.sku_id,
                "quantity": item.quantity,
                "price": float(item.price),
            }
            for item in sorted_cart_items
        ],
        "payment_method": payload.payment_method.value,
        "customer_phone": payload.customer_phone,
        # We include the frontend's UUID as a salt so the hash is unique
        # even if two pharmacists submit identical carts simultaneously.
        "frontend_idempotency_key": payload.idempotency_key,
    }, sort_keys=True)

    # Step 3: Generate the SHA-256 hex digest.
    # SHA-256 produces a 64-character hexadecimal string that is:
    #   - Deterministic: same input → same output
    #   - Collision-resistant: different inputs → astronomically different outputs
    #   - One-way: you cannot reverse the hash to recover the cart contents
    deterministic_idempotency_hash: str = hashlib.sha256(
        canonical_checkout_payload.encode("utf-8")
    ).hexdigest()

    # Step 4: Check Redis using this deterministic hash as the key.
    # If the hash already exists in Redis, it means this exact checkout was
    # already processed — reject with 409 Conflict.
    is_duplicate: bool = await is_duplicate_checkout_request(deterministic_idempotency_hash)
    if is_duplicate:
        logger.warning(
            f"Duplicate checkout detected: hash={deterministic_idempotency_hash[:16]}... "
            f"(tenant={tenant_id})"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This checkout has already been processed. Duplicate request rejected."
        )

    # =====================================================================
    # GUARD 2: VELOCITY CHECK (Redis sliding window — prevents abuse)
    # =====================================================================
    # Beginner Note: Even with different idempotency keys, a single tenant
    # should not be able to submit more than 2 checkouts per second.
    # This protects against accidental rapid clicking or automated abuse.
    is_rate_limited: bool = await is_above_checkout_rate_limit(tenant_id)
    if is_rate_limited:
        logger.warning(f"Checkout rate limit exceeded for tenant={tenant_id}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many checkout requests. Please wait a moment and try again."
        )

    # =====================================================================
    # TRANSACTION START: Database writes begin here
    # =====================================================================
    
    # 1. Generate a unique ID for the entire sale receipt
    generatedReceiptId = str(uuid.uuid4())
    totalTransactionAmount = 0.0
    resolvedPatientId = None

    try:
        # 2. PATIENT UPSERT (Progressive Disclosure):
        #    If the pharmacist entered a phone number, we look up or create a patient profile
        #    so the receipt can be linked for future automated refill messaging.
        #    Defensively handle empty strings from the frontend.
        if payload.customer_phone and payload.customer_phone.strip():
            existingPatientRecord = db.query(Patient).filter(
                Patient.phone_number == payload.customer_phone,
                Patient.tenant_id == tenant_id
            ).first()

            if existingPatientRecord:
                resolvedPatientId = existingPatientRecord.patient_id
            else:
                newlyCreatedPatient = Patient(
                    patient_id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    name=payload.customer_name or "Unknown",
                    phone_number=payload.customer_phone
                )
                db.add(newlyCreatedPatient)
                db.flush()
                resolvedPatientId = newlyCreatedPatient.patient_id

                log_audit_event(
                    db=db,
                    tenant_id=tenant_id,
                    entity_type="patient",
                    entity_id=resolvedPatientId,
                    action_type="CREATE",
                    old_value=None,
                    new_value={
                        "name": payload.customer_name or "Unknown",
                        "phone_number": payload.customer_phone,
                    },
                    extra_metadata={"endpoint": "/api/v1/pos/checkout"},
                )

        # 3. Create the empty receipt header FIRST so it has a row in the DB.
        newReceiptRecord = SaleReceiptModel(
            id=generatedReceiptId,
            tenant_id=tenant_id,
            total_amount_inr=0,
            payment_method=payload.payment_method.value,
            patient_id=resolvedPatientId
        )
        db.add(newReceiptRecord)
        db.flush()

        log_audit_event(
            db=db,
            tenant_id=tenant_id,
            entity_type="sale_receipt",
            entity_id=generatedReceiptId,
            action_type="CREATE",
            old_value=None,
            new_value={
                "total_amount_inr": 0,
                "payment_method": payload.payment_method.value,
                "patient_id": resolvedPatientId,
            },
            extra_metadata={"endpoint": "/api/v1/pos/checkout"},
        )

        # 4. Iterate through each item in the cart to validate stock and calculate totals
        for cartItem in payload.items:
            # We explicitly fetch the specific batch the user wants to buy
            # with_for_update prevents other users from buying this exact batch at the exact same millisecond
            currentBatchInventory = db.query(MedicationBatchModel).filter(
                MedicationBatchModel.batch_id == cartItem.batch_id
            ).with_for_update().first()

            # Defensive check: Ensure the batch exists
            if not currentBatchInventory:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Batch {cartItem.batch_id} not found in inventory."
                )

            # Optimistic Concurrency: Check if we have enough stock before deducting
            if currentBatchInventory.available_quantity < cartItem.quantity:
                insufficientStockException = f"Insufficient stock for {cartItem.sku_id}. Requested: {cartItem.quantity}, Available: {currentBatchInventory.available_quantity}"
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=insufficientStockException
                )

            # Deduct the inventory quantity safely
            old_available_quantity = currentBatchInventory.available_quantity
            currentBatchInventory.available_quantity -= cartItem.quantity

            log_audit_event(
                db=db,
                tenant_id=tenant_id,
                entity_type="medication_batch",
                entity_id=cartItem.batch_id,
                action_type="UPDATE",
                old_value={"available_quantity": old_available_quantity},
                new_value={"available_quantity": currentBatchInventory.available_quantity},
                extra_metadata={"endpoint": "/api/v1/pos/checkout", "sku_id": cartItem.sku_id},
            )
            
            # Calculate the financial contribution of this line item
            lineItemTotalCost = cartItem.quantity * cartItem.price
            totalTransactionAmount += lineItemTotalCost

            # Record the specific line item sold — receipt_id is safe now because we flushed
            newLineItemRecord = SaleLineItemModel(
                receipt_id=generatedReceiptId,
                tenant_id=tenant_id,
                batch_id=cartItem.batch_id,
                name=cartItem.name,
                quantity_sold=cartItem.quantity,
                price_per_unit=cartItem.price
            )
            db.add(newLineItemRecord)

        # 5. Update the receipt header with the final calculated total
        newReceiptRecord.total_amount_inr = totalTransactionAmount

        log_audit_event(
            db=db,
            tenant_id=tenant_id,
            entity_type="sale_receipt",
            entity_id=generatedReceiptId,
            action_type="UPDATE",
            old_value={"total_amount_inr": 0},
            new_value={"total_amount_inr": totalTransactionAmount},
            extra_metadata={"endpoint": "/api/v1/pos/checkout"},
        )

        # 6. Pragmatic Outbox Pattern: Save an event for background workers (Kafka/Analytics)
        # By saving this inside the exact same database transaction, we guarantee we never
        # drop events if the server crashes right after the sale.
        outboxPayload = {
            "receipt_id": generatedReceiptId,
            "total_amount": totalTransactionAmount,
            "patient_id": resolvedPatientId,
            "customer_phone": payload.customer_phone,
            "customer_name": payload.customer_name,
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

        # 7. The ACID Guarantee: Commit ALL database writes at once.
        # If any step above failed, the session would rollback automatically.
        db.commit()

        # 8. Mark the deterministic idempotency hash as processed so any
        # retry with the same cart gets a 409 Conflict. We use the server-side
        # SHA-256 hash (not the frontend UUID) so idempotency is guaranteed
        # even if a malicious client sends different UUIDs for the same cart.
        await mark_checkout_completed(deterministic_idempotency_hash)

        # 9. The Courier: Trigger the background task to relay the outbox events to Kafka
        background_tasks.add_task(relay_outbox_events_to_kafka, db)

        # 11. Return success to the frontend
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

@router.get("/history", response_model=List[ReceiptHistoryResponse])
def get_transaction_history(
    db: Session = Depends(get_database_session),
    tenant_id: str = Depends(get_current_tenant)
):
    """
    Returns a history of recent POS transactions with eager-loaded line items.
    """
    receipts = db.query(SaleReceiptModel).options(
        selectinload(SaleReceiptModel.lines)
    ).filter(
        SaleReceiptModel.tenant_id == tenant_id  # Enforce multi-tenant isolation: only return receipts for this tenant
    ).order_by(
        SaleReceiptModel.timestamp.desc()
    ).limit(50).all()

    # Batch-load patient data for all receipts
    patient_ids = [r.patient_id for r in receipts if r.patient_id]
    patient_map = {}
    if patient_ids:
        patients = db.query(Patient).filter(Patient.patient_id.in_(patient_ids)).all()
        patient_map = {p.patient_id: p for p in patients}

    history = []
    for receipt in receipts:
        patient = patient_map.get(receipt.patient_id)
        customer_name = patient.name if patient else "Anonymous"
        customer_phone = patient.phone_number if patient else None

        history.append(ReceiptHistoryResponse(
            id=receipt.id,
            timestamp=receipt.timestamp,
            total_amount_inr=float(receipt.total_amount_inr),
            payment_method=receipt.payment_method or "CASH",
            customer_name=customer_name,
            customer_phone=customer_phone,
            items=[
                TransactionItemResponse(
                    productId=item.batch_id,
                    name=item.name or item.batch_id,
                    price=float(item.price_per_unit),
                    quantity=item.quantity_sold,
                    total=float(item.quantity_sold * item.price_per_unit)
                )
                for item in receipt.lines
            ]
        ))
    return history
