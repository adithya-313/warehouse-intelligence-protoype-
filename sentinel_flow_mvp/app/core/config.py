"""Environment variables and configuration management.

This module provides centralized configuration management for the application.
Non-sensitive settings are loaded from a ``.env`` file using pydantic-settings.
Sensitive values (API keys, tokens) are overlaid from the secrets vault
(``.secrets.json`` by default) so they are never committed to version control.

The priority order for any given key is:
    1. Environment variable (highest — used in production/Kubernetes)
    2. ``.env`` file (local development)
    3. Secrets vault (``.secrets.json`` file — local development)
    4. Pydantic field default (lowest)
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApplicationSettings(BaseSettings):
    """Application settings loaded from environment variables.

    Attributes:
        application_name: The name of the application.
        application_version: The current version of the application.
        debug_mode: Whether debug mode is enabled.
        database_url: The database connection URL.
        api_key: The API key for authentication.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    application_name: str = Field(
        default="Sentinel-Flow",
        description="The name of the application",
    )

    application_version: str = Field(
        default="0.1.0",
        description="The current version of the application",
    )

    debug_mode: bool = Field(
        default=False,
        description="Whether debug mode is enabled",
    )

    database_url: Optional[str] = Field(
        default=None,
        description="The database connection URL",
    )

    api_key: Optional[str] = Field(
        default=None,
        description="The API key for authentication",
    )

    # Phase 15.2: Google Gemini API Key for RAG Pipeline
    GEMINI_API_KEY: str | None = Field(default=None, description="Google Gemini API Key")

    WEATHER_API_KEY: str | None = Field(default=None, description="Weather API Key")
    TRENDS_API_KEY: str | None = Field(default=None, description="Search Trends API Key")

    REDIS_URL: str = Field(
        default="redis://redis:6379/0",
        description="The Redis connection URL for Celery broker and pub/sub",
    )

    KAFKA_BOOTSTRAP_SERVERS: str = Field(
        default="redpanda:9092",
        description="Kafka bootstrap servers",
    )

    ML_TRAIN_BATCH_SIZE: int = Field(
        default=4,
        description="Batch size for ML training loops",
    )

    ML_TRAIN_EPOCHS: int = Field(
        default=5,
        description="Number of epochs for ML training",
    )

    ML_LEARNING_RATE: float = Field(
        default=3e-4,
        description="Learning rate for ML models",
    )

    ML_GRADIENT_ACCUMULATION_STEPS: int = Field(
        default=4,
        description="Number of steps to accumulate gradients before taking an optimizer step",
    )

    ADAPTER_STORAGE_PATH: str = Field(
        default="/app/data/adapters",
        description="Directory to store adapter weight files.",
    )

    # This is the ONE place that decides which Chronos time-series model we load.
    # Every part of the app (API server, background worker, LoRA training) reads
    # from this single value — so we never again end up with two different models
    # loaded in two different places by accident.
    CHRONOS_MODEL_NAME: str = Field(
        default="amazon/chronos-t5-mini",
        description="HuggingFace model identifier for the Chronos time-series foundation model.",
    )

    # Geographic Fallbacks (Defaulting to Kochi, Kerala for initial launch)
    FALLBACK_LAT: float = Field(default=9.9312, description="Fallback latitude")
    FALLBACK_LON: float = Field(default=76.2673, description="Fallback longitude")
    FALLBACK_CITY: str = Field(default="Kochi", description="Fallback city")

    # REDIS_URL defined above as a proper Pydantic Field

    def model_post_init(self, __context) -> None:
        """Overlay secrets from the vault after loading from ``.env``.

        This allows running the application without ``GEMINI_API_KEY`` or
        ``WEATHER_API_KEY`` in ``.env`` — they are pulled from the vault file
        instead. Environment variables still take precedence because pydantic-
        settings evaluates them first.
        """
        _VAULT_KEYS = ("GEMINI_API_KEY", "WEATHER_API_KEY", "TRENDS_API_KEY", "API_KEY")
        try:
            from app.core.vault import get_vault

            vault = get_vault()
            for key in _VAULT_KEYS:
                if not getattr(self, key, None):
                    vault_value = vault.get(key)
                    if vault_value:
                        object.__setattr__(self, key, vault_value)
        except Exception:
            pass  # Vault unavailable — use whatever .env provided

@lru_cache
def get_application_settings() -> ApplicationSettings:
    """Get the cached application settings.

    This function returns a cached instance of ApplicationSettings.
    The settings are loaded once and cached for subsequent calls.

    Returns:
        An instance of ApplicationSettings with all configuration loaded.
    """
    return ApplicationSettings()