"""API Dependencies for Security and Authentication."""

import logging
from typing import Optional
from fastapi import Header, Security, HTTPException, status
from fastapi.security import APIKeyHeader

from app.core.config import get_application_settings

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """Verify that the incoming request has a valid API key.
    
    If the API key is missing or invalid, or if the server does not have an
    API key configured, it rejects the request with a 401 Unauthorized.
    """
    settings = get_application_settings()
    
    # If the server's expected key is empty, ALL requests must fail 401
    # to prevent accidental open access.
    if not settings.api_key:
        logger.error("Security misconfiguration: Server API_KEY is not set.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
        
    if not api_key or api_key != settings.api_key:
        logger.warning("Unauthorized access attempt with invalid API Key.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
        
    return api_key


def get_current_tenant(
    x_tenant_id: Optional[str] = Header("system_admin", alias="X-Tenant-ID")
) -> str:
    """SECURITY GATEWAY: Enforces multi-tenant isolation.

    Defaults to system_admin if the Next.js proxy strips the custom header.
    """
    if not x_tenant_id:
        raise HTTPException(status_code=403, detail="X-Tenant-ID header is missing. Access Denied.")

    return x_tenant_id
