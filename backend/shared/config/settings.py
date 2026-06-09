"""
Purpose: Centralized application settings via Pydantic Settings.
Future responsibilities: Load env vars; expose typed config to all services.
Service ownership: Shared module (all backend services).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration — TODO: split per-service overrides if needed."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "mannerai-meetings"
    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/mannerai_meetings"
    database_pool_size: int = 10
    database_echo: bool = False
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    openai_api_key: str | None = None
    gemini_api_key: str | None = None

    # TODO: meeting_service_url, ai_service_url, etc.


def get_settings() -> Settings:
    """Dependency-injection friendly settings factory."""
    # TODO: cache with lru_cache for production
    return Settings()
