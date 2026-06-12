"""Supply-Graph Weighted Aggregation (SGWA) Service.

This is the mathematical defense layer for the hub-and-spoke federated
architecture. Supplier edge nodes push local model weights to the hub,
and this service sanitises those updates using a Trimmed Mean strategy
before the aggregated result is applied to the global model.

Trimmed Mean defence strategy:
    1.  Stack all incoming weight vectors into a 2-D NumPy array.
    2.  For each parameter column, compute the median and std across
        all supplier nodes.
    3.  Flag any node where *any* of its weights deviate more than
        2 standard deviations from the column median.
    4.  Exclude all flagged (poisoned / anomalous) nodes.
    5.  Average the remaining safe weight vectors element-wise.
    6.  Return the aggregated flat list.  If every node is excluded,
        raise ValueError because no safe signal remains.
"""

import logging
from typing import List

import numpy as np

from app.domain.schemas import FederatedWeightPayload

logger = logging.getLogger(__name__)

# Number of standard deviations from the median used as the
# inclusion threshold for the Trimmed Mean defence.
# Weights falling outside median ± (Z_THRESHOLD × std) are
# considered anomalous and the submitting node is excluded.
Z_THRESHOLD: float = 2.0


class SGWAService:
    """Stateless service that applies Trimmed Mean aggregation to
    federated weight updates from supplier edge nodes."""

    @staticmethod
    def aggregate_weights(
        weight_payloads: List[FederatedWeightPayload],
    ) -> List[float]:
        """Aggregate multiple supplier weight updates using a Trimmed Mean.

        Args:
            weight_payloads:
                list of validated weight payloads, one per edge node.

        Returns:
            A single flat list of aggregated weights.

        Raises:
            ValueError:
                If *weight_payloads* is empty, or if every submitted
                update is flagged as anomalous.
        """
        if not weight_payloads:
            raise ValueError(
                "At least one supplier weight payload is required "
                "for aggregation."
            )

        # ------------------------------------------------------------------
        # Step 1: Stack all weight vectors into a 2-D array.
        #         Shape: (n_suppliers, n_weights_per_node)
        # ------------------------------------------------------------------
        stacked: np.ndarray = np.array(
            [p.weights for p in weight_payloads],
            dtype=np.float64,
        )
        n_suppliers, n_weights = stacked.shape

        # ------------------------------------------------------------------
        # Step 2: Single-supplier fast-path.
        #         When only one node submits, there is nothing to compare
        #         or aggregate — return its weights verbatim.
        # ------------------------------------------------------------------
        if n_suppliers == 1:
            logger.info(
                "Single supplier weight payload received — "
                "returning unchanged."
            )
            return weight_payloads[0].weights

        # ------------------------------------------------------------------
        # Step 3: Compute column-wise median and standard deviation.
        #         The median is more robust to outliers than the mean,
        #         making it a better centre estimate for outlier detection.
        # ------------------------------------------------------------------
        column_medians: np.ndarray = np.median(stacked, axis=0)
        column_stds: np.ndarray = np.std(stacked, axis=0)

        # ------------------------------------------------------------------
        # Step 4: Guard against division by zero.
        #         If every supplier submitted the *exact same* value for a
        #         given parameter, std == 0.  Replace it with 1.0 so the
        #         z-score calculation does not produce Inf.
        # ------------------------------------------------------------------
        safe_stds: np.ndarray = np.where(column_stds == 0.0, 1.0, column_stds)

        # ------------------------------------------------------------------
        # Step 5: Compute per-weight deviation in units of standard
        #         deviation from the column median (robust z-score).
        # ------------------------------------------------------------------
        deviations: np.ndarray = np.abs(stacked - column_medians) / safe_stds

        # ------------------------------------------------------------------
        # Step 6: Flag any supplier node where *at least one* weight
        #         exceeds Z_THRESHOLD standard deviations from the median.
        #         A single poisoned gradient is sufficient to distrust the
        #         entire update from that node.
        # ------------------------------------------------------------------
        toxic_mask: np.ndarray = np.any(deviations > Z_THRESHOLD, axis=1)

        n_flagged: int = int(np.sum(toxic_mask))
        if n_flagged > 0:
            logger.warning(
                f"Trimmed Mean flagged {n_flagged} of {n_suppliers} "
                f"supplier updates as anomalous."
            )

        # ------------------------------------------------------------------
        # Step 7: Keep only safe (non-flagged) weight vectors.
        # ------------------------------------------------------------------
        safe_weights: np.ndarray = stacked[~toxic_mask]

        # ------------------------------------------------------------------
        # Step 8: If every node was flagged, we have no trustworthy signal.
        # ------------------------------------------------------------------
        if safe_weights.shape[0] == 0:
            raise ValueError(
                "All supplier weight updates were flagged as anomalous. "
                "No safe weights remain to aggregate."
            )

        # ------------------------------------------------------------------
        # Step 9: Element-wise average of the surviving (safe) weight
        #         vectors.  This is the final Trimmed Mean result.
        # ------------------------------------------------------------------
        aggregated: np.ndarray = np.mean(safe_weights, axis=0)

        logger.info(
            f"Aggregated {safe_weights.shape[0]} safe weight vectors "
            f"into a single model update."
        )

        return aggregated.tolist()
