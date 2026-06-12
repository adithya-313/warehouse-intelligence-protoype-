"""Custom error handling classes.

This module defines custom exception classes for the application.
All exceptions follow a consistent structure for API error responses.
"""

from typing import Any, Optional
from fastapi import HTTPException, status


class SentinelFlowBaseException(Exception):
    """Base exception class for Sentinel-Flow application.

    This class serves as the base for all custom exceptions in the application.
    It provides a consistent structure for error handling.
    """

    def __init__(
        self,
        message: str,
        error_code: str,
        details: Optional[Any] = None,
    ) -> None:
        """Initialize the base exception.

        Args:
            message: A human-readable error message.
            error_code: A machine-readable error code.
            details: Additional details about the error.
        """
        self.message = message
        self.error_code = error_code
        self.details = details
        super().__init__(message)


class ValidationException(SentinelFlowBaseException):
    """Exception raised for validation errors.

    This exception is raised when input validation fails.
    """

    def __init__(
        self,
        message: str = "Validation error occurred",
        error_code: str = "VALIDATION_ERROR",
        details: Optional[Any] = None,
    ) -> None:
        """Initialize the validation exception.

        Args:
            message: A human-readable error message.
            error_code: A machine-readable error code.
            details: Additional details about the validation error.
        """
        super().__init__(
            message=message,
            error_code=error_code,
            details=details,
        )


class ProcessingException(SentinelFlowBaseException):
    """Exception raised during data processing.

    This exception is raised when an error occurs during data processing.
    """

    def __init__(
        self,
        message: str = "Processing error occurred",
        error_code: str = "PROCESSING_ERROR",
        details: Optional[Any] = None,
    ) -> None:
        """Initialize the processing exception.

        Args:
            message: A human-readable error message.
            error_code: A machine-readable error code.
            details: Additional details about the processing error.
        """
        super().__init__(
            message=message,
            error_code=error_code,
            details=details,
        )


def raise_http_exception(
    status_code: int,
    message: str,
    error_code: str,
    details: Optional[Any] = None,
) -> None:
    """Raise an HTTPException with the given parameters.

    This function raises a FastAPI HTTPException with the given status code,
    message, error code, and details.

    Args:
        status_code: The HTTP status code to return.
        message: A human-readable error message.
        error_code: A machine-readable error code.
        details: Additional details about the error.

    Raises:
        HTTPException: The HTTP exception with the specified parameters.
    """
    raise HTTPException(
        status_code=status_code,
        detail={
            "message": message,
            "error_code": error_code,
            "details": details,
        },
    )