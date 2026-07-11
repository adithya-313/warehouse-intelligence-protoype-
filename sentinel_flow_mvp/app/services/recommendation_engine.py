from sqlalchemy.orm import Session
from app.infrastructure.models import MedicationModel, MedicationBatchModel
import logging

logger = logging.getLogger(__name__)

def get_clinical_cross_sells(db: Session, sku_id: str, top_k: int = 2):
    """
    Finds medicines frequently bought with the scanned item using Market Basket Analysis.
    """
    from app.infrastructure.models import SaleLineItemModel, MedicationBatchModel
    
    # 1. Market Basket Analysis - Step A: Find all receipts that contain the target SKU.
    # We join SaleLineItemModel with MedicationBatchModel because the line item only holds the batch_id,
    # and we need to match against the parent sku_id.
    receipts_with_sku = db.query(SaleLineItemModel.receipt_id).join(
        MedicationBatchModel, SaleLineItemModel.batch_id == MedicationBatchModel.batch_id
    ).filter(
        MedicationBatchModel.sku_id == sku_id
    ).all()
    
    # We extract just the receipt IDs into a simple list.
    target_receipt_ids = [row.receipt_id for row in receipts_with_sku]
    
    # If this item has never been sold, we can't recommend anything based on sales history.
    if not target_receipt_ids:
        return []
        
    # 2. Market Basket Analysis - Step B: Find all OTHER items sold on those exact same receipts.
    # We query the line items again, filtering by the receipt IDs we just found,
    # but we EXCLUDE the original sku_id so we don't recommend the item to itself.
    co_purchased_items = db.query(MedicationBatchModel.sku_id).join(
        SaleLineItemModel, SaleLineItemModel.batch_id == MedicationBatchModel.batch_id
    ).filter(
        SaleLineItemModel.receipt_id.in_(target_receipt_ids),
        MedicationBatchModel.sku_id != sku_id
    ).all()
    
    # 3. Market Basket Analysis - Step C: Count the frequencies of the co-purchased items.
    # We use a dictionary to tally how many times each item was bought alongside our target item.
    frequency_map = {}
    for item in co_purchased_items:
        co_sku = item.sku_id
        if co_sku in frequency_map:
            frequency_map[co_sku] += 1
        else:
            frequency_map[co_sku] = 1
            
    # 4. Calculate Confidence Scores and Format Results
    # The total number of receipts where the target item was sold represents 100% (the denominator).
    # We divide the co-purchase count by the total receipts to get the confidence percentage.
    total_receipts_count = len(target_receipt_ids)
    results = []
    
    for co_sku, count in frequency_map.items():
        confidence_score = count / total_receipts_count
        results.append({
            "recommended_sku": co_sku,
            "confidence_score": confidence_score
        })
        
    # Finally, we sort the recommendations from highest confidence to lowest, and return the top K.
    results.sort(key=lambda x: x["confidence_score"], reverse=True)
    return results[:top_k]


# --- 2. The Generic Conversion Engine (Margin Maximization) ---
def get_high_margin_generics(db: Session, sku_id: str):
    """
    Finds cheaper generic alternatives with the exact same active ingredients,
    sorted by which one makes the pharmacy the most profit.
    """
    # 1. Find the original scanned medication
    original_med = db.query(MedicationModel).filter(MedicationModel.sku_id == sku_id).first()
    if not original_med or not original_med.apis:
        return []
        
    # 2. Find other medications with the EXACT same Active Pharmaceutical Ingredients (APIs)
    # Beginner Note: We exclude the original scanned item from the results.
    alternatives = db.query(MedicationModel).filter(
        MedicationModel.apis == original_med.apis,
        MedicationModel.sku_id != sku_id
    ).all()
    
    alt_sku_ids = [alt.sku_id for alt in alternatives]
    if not alt_sku_ids:
        return []
        
    # 3. Calculate the Profit Score for available batches of these alternatives
    # Profit Score = Max Retail Price (MRP) - Cost Price
    results = []
    for alt_sku in alt_sku_ids:
        # Find the batch that yields the highest profit margin
        best_batch = db.query(MedicationBatchModel).filter(
            MedicationBatchModel.sku_id == alt_sku,
            MedicationBatchModel.available_quantity > 0
        ).order_by((MedicationBatchModel.max_retail_price - MedicationBatchModel.cost_price).desc()).first()
        
        if best_batch:
            profit = float(best_batch.max_retail_price - best_batch.cost_price)
            results.append({
                "sku_id": alt_sku,
                "batch_id": best_batch.batch_id,
                "profit_score": profit,
                "mrp": float(best_batch.max_retail_price),
                "cost": float(best_batch.cost_price)
            })
            
    # Sort the results so the highest profit item is at the top of the list
    results.sort(key=lambda x: x["profit_score"], reverse=True)
    return results
