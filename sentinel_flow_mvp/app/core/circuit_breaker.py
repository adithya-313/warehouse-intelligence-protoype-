"""Aegis Lite Circuit Breaker.

Implements a circuit breaker pattern to prevent cascade failures when the ML service is unavailable.
"""

import logging
import time
from enum import Enum
from typing import Any, Dict, Optional

from app.services.ml_service import generate_mock_stockout_prediction

logger = logging.getLogger(__name__)


class CircuitStateEnum(str, Enum):
    """Enumeration of circuit breaker states.

    Attributes:
        CLOSED: Normal operation, requests pass through.
        OPEN: Circuit is open, requests fail fast.
        HALF_OPEN: Testing if service recovered.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class AegisLiteCircuitBreaker:
    """Circuit breaker implementation for ML service protection.

    Attributes:
        failure_threshold: Number of failures before opening the circuit.
        recovery_timeout: Seconds to wait before attempting recovery.
        success_threshold: Number of successes in half-open before closing.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        success_threshold: int = 2,
    ) -> None:
        """Initialize the circuit breaker.

        Args:
            failure_threshold: Number of failures before opening the circuit.
            recovery_timeout: Seconds to wait before attempting recovery.
            success_threshold: Number of successes needed to close the circuit.
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self.current_state = CircuitStateEnum.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None

    def call_ml_service(
        self,
        supplier_id: str,
        inventory_count: int,
        delivery_delay_days: int,
    ) -> Dict[str, Any]:
        """Execute the ML service call with circuit breaker protection.

        Args:
            supplier_id: The unique identifier for the supplier.
            inventory_count: Current inventory count.
            delivery_delay_days: Delivery delay in days.

        Returns:
            The ML prediction dictionary.

        Raises:
            Exception: If the circuit is open or ML service fails.
        """
        if self.current_state == CircuitStateEnum.OPEN:
            if self._should_attempt_recovery():
                self.current_state = CircuitStateEnum.HALF_OPEN
                logger.info("Circuit half-open: attempting recovery")
            else:
                raise Exception("Circuit breaker is OPEN: ML service unavailable")

        try:
            result = generate_mock_stockout_prediction(
                supplier_id_string=supplier_id,
                current_inventory=inventory_count,
                delivery_delay=delivery_delay_days,
            )
            self._on_success()
            return result

        except Exception as exception:
            self._on_failure()
            raise exception

    def _should_attempt_recovery(self) -> bool:
        """Check if enough time has passed to attempt recovery.

        Returns:
            True if recovery should be attempted.
        """
        if self.last_failure_time is None:
            return True
        elapsed = time.time() - self.last_failure_time
        return elapsed >= self.recovery_timeout

    def _on_success(self) -> None:
        """Handle successful ML service call."""
        if self.current_state == CircuitStateEnum.HALF_OPEN:
            self.success_count = self.success_count + 1
            if self.success_count >= self.success_threshold:
                self.current_state = CircuitStateEnum.CLOSED
                self.failure_count = 0
                self.success_count = 0
                logger.info("Circuit breaker CLOSED: service recovered")
        else:
            self.failure_count = 0

    def _on_failure(self) -> None:
        """Handle failed ML service call."""
        self.failure_count = self.failure_count + 1
        self.last_failure_time = time.time()

        if self.current_state == CircuitStateEnum.HALF_OPEN:
            self.current_state = CircuitStateEnum.OPEN
            self.success_count = 0
            logger.warning("Circuit breaker re-OPENED: half-open test failed")
        elif self.failure_count >= self.failure_threshold:
            self.current_state = CircuitStateEnum.OPEN
            logger.warning("Circuit breaker OPENED: failure threshold reached")


_circuit_breaker_instance: Optional[AegisLiteCircuitBreaker] = None


def get_circuit_breaker() -> AegisLiteCircuitBreaker:
    """Get the singleton circuit breaker instance.

    Returns:
        The AegisLiteCircuitBreaker singleton.
    """
    global _circuit_breaker_instance

    if _circuit_breaker_instance is None:
        _circuit_breaker_instance = AegisLiteCircuitBreaker()

    return _circuit_breaker_instance