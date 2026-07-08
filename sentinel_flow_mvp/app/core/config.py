"""Environment variables and configuration management.

This module provides centralized configuration management for the application.
All environment variables are loaded from a .env file using pydantic settings.
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

    redis_url: str = Field(
        default="redis://localhost:6379/0",
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

    # Geographic Fallbacks (Defaulting to Kochi, Kerala for initial launch)
    FALLBACK_LAT: float = Field(default=9.9312, description="Fallback latitude")
    FALLBACK_LON: float = Field(default=76.2673, description="Fallback longitude")
    FALLBACK_CITY: str = Field(default="Kochi", description="Fallback city")

    @property
    def REDIS_URL(self) -> str:
        return self.redis_url

@lru_cache
def get_application_settings() -> ApplicationSettings:
    """Get the cached application settings.

    This function returns a cached instance of ApplicationSettings.
    The settings are loaded once and cached for subsequent calls.

    Returns:
        An instance of ApplicationSettings with all configuration loaded.
    """
    return ApplicationSettings()