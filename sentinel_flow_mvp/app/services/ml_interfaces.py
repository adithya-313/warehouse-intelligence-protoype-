"""Machine Learning Module Interfaces.

This module defines the abstract base class that all prediction modules must implement.
It enforces a strict contract for both primary model inference and heuristic fallback,
ensuring consistent behavior across all 14 upcoming intelligence modules.

The Strategy Pattern is used here to allow the PredictionOrchestrator to swap
between different model implementations without changing its core routing logic.

All methods are asynchronous to support non-blocking I/O operations like
database queries, external API calls, and simulated heavy computation.
"""

from abc import ABC, abstractmethod

from app.domain.schemas import BaseInferenceRequest, StandardizedPredictionResponse


class BasePredictionModule(ABC):
    """Abstract base class for all prediction modules in Sentinel-Flow.

    Every intelligence module (e.g., demand forecasting, fuel cost prediction,
    supplier risk scoring) must inherit from this class and implement both
    the primary prediction method and the fallback heuristic.

    This design guarantees that:
    1. All modules accept the same input format (BaseInferenceRequest).
    2. All modules return the same output format (StandardizedPredictionResponse).
    3. Every module has a safe fallback path if the ML model crashes or times out.
    4. All operations are asynchronous for non-blocking execution.
    """

    @abstractmethod
    async def predict(self, request: BaseInferenceRequest) -> StandardizedPredictionResponse:
        """Execute the primary machine learning model inference.

        This method contains the actual ML model logic (e.g., XGBoost, PyTorch,
        or external API call). It must return a StandardizedPredictionResponse
        with the model's prediction and confidence score.

        Args:
            request: The standardized inference request containing features and metadata.

        Returns:
            A StandardizedPredictionResponse with the model's output.

        Raises:
            Exception: If the model fails, times out, or encounters invalid input.
                       The orchestrator will catch this and trigger the fallback.
        """
        pass

    @abstractmethod
    async def heuristic_fallback(self, request: BaseInferenceRequest) -> StandardizedPredictionResponse:
        """Execute a deterministic heuristic when the primary model fails.

        This method provides a safe, rule-based fallback prediction that ensures
        the system continues operating even during ML outages. Heuristics should
        be simple, fast, and based on historical averages or business rules.

        Args:
            request: The standardized inference request containing features and metadata.

        Returns:
            A StandardizedPredictionResponse with fallback_engaged=True.
        """
        pass
