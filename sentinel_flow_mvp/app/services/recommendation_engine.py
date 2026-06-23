import networkx as nx
from sqlalchemy.orm import Session
from app.infrastructure.models import MedicationModel, MedicationBatchModel
import logging

logger = logging.getLogger(__name__)

# --- 1. The Lightweight Graph Engine (Cross-Selling) ---
# Beginner Note: A Graph is just a web of connections. Nodes are medicines. 
# Edges are the lines connecting them. The 'weight' of the line is how often they are bought together.
co_purchase_graph = nx.Graph()

# Mocking some historical data for the MVP. In production, a background worker 
# would constantly update these weights based on actual Kafka POS events.
co_purchase_graph.add_edge("SKU-AMOXICILLIN", "SKU-PROBIOTIC", weight=0.85)
co_purchase_graph.add_edge("SKU-METFORMIN", "SKU-B12-VITAMIN", weight=0.72)

def get_clinical_cross_sells(sku_id: str, top_k: int = 2):
    """
    Finds medicines frequently bought with the scanned item using Graph connections.
    """
    if sku_id not in co_purchase_graph:
        return []
        
    # Get all connected medicines and sort them by the 'weight' (confidence score)
    neighbors = co_purchase_graph[sku_id].items()
    sorted_neighbors = sorted(neighbors, key=lambda x: x[1]['weight'], reverse=True)
    
    # Return the top K recommendations
    return [{"recommended_sku": n[0], "confidence_score": n[1]['weight']} for n in sorted_neighbors[:top_k]]


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
