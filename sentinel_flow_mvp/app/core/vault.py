"""File-based secrets vault for environment-agnostic secret management.

Beginner Note:
    In production, environment variables are the most common way to pass secrets
    to an application (e.g., Kubernetes Secrets → env vars). However, during local
    development, managing a long list of env vars is tedious and error-prone.
    
    This vault bridges the gap: it reads secrets from a JSON file (`.secrets.json`
    by default), separate from the non-sensitive config in `.env`. The file path
    can be overridden with the ``VAULT_PATH`` environment variable for environments
    that mount secrets as files (Kubernetes, Docker secrets, etc.).
    
    The vault is a singleton — loaded once when ``get_vault()`` is first called.
    
Usage:
    from app.core.vault import get_secret
    
    gemini_key = get_secret("GEMINI_API_KEY")
    if gemini_key:
        genai.configure(api_key=gemini_key)
"""

import json
import logging
import os
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_VAULT_PATH: str = ".secrets.json"


class SecretsVault:
    """Lightweight file-based vault that loads secrets from a JSON file.

    The vault file is never read until the first call to ``get()`` or
    ``load()``. This allows the application to start even when the vault
    file does not exist — secrets simply return ``None``.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        """Initialize the vault with an optional custom path.

        Args:
            path: Absolute or relative path to the JSON secrets file.
                  Defaults to ``DEFAULT_VAULT_PATH`` (``.secrets.json``).
                  Falls back to the ``VAULT_PATH`` environment variable if set.
        """
        self._path: str = path or os.environ.get("VAULT_PATH", DEFAULT_VAULT_PATH)
        self._secrets: dict[str, str] = {}
        self._loaded: bool = False

    def load(self) -> None:
        """Read the secrets file from disk into memory.

        This is called automatically on the first ``get()``, but you may
        call it explicitly to fail early if the vault file is required.
        """
        if self._loaded:
            return

        if os.path.exists(self._path):
            try:
                with open(self._path, encoding="utf-8") as file_handle:
                    self._secrets = json.load(file_handle)
                logger.info(
                    "Vault loaded %d secret(s) from %s.",
                    len(self._secrets),
                    self._path,
                )
            except (json.JSONDecodeError, PermissionError, OSError) as error:
                logger.warning(
                    "Vault file %s exists but could not be read: %s. "
                    "Secrets will be unavailable.",
                    self._path,
                    error,
                )
        else:
            logger.debug(
                "Vault file %s not found. "
                "Only environment-variable-based secrets will be available.",
                self._path,
            )

        self._loaded = True

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Retrieve a secret by key.

        Args:
            key: The secret name (must match exactly, case-sensitive).
            default: Value to return if the key is not found (default: ``None``).

        Returns:
            The secret value, or ``default`` if not found.
        """
        if not self._loaded:
            self.load()
        return self._secrets.get(key, default)

    def __contains__(self, key: str) -> bool:
        if not self._loaded:
            self.load()
        return key in self._secrets


# ------------------------------------------------------------------
# Module-level singleton — cached so we only read the file once
# ------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_vault() -> SecretsVault:
    """Return the global SecretsVault singleton (lazily loaded)."""
    return SecretsVault()


def get_secret(key: str, default: Optional[str] = None) -> Optional[str]:
    """Convenience function: get a secret from the global vault singleton.

    Args:
        key: The secret name.
        default: Fallback value if not found.

    Returns:
        The secret value, or ``default``.
    """
    return get_vault().get(key, default)
