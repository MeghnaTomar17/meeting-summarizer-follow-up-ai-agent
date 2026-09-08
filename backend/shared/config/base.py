"""
Purpose: Shared base settings for all backend services.
Service ownership: Shared module (cross-cutting configuration only).
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from pydantic_settings.sources import DotEnvSettingsSource

_REPO_ROOT_MARKERS = (".env.example", "requirements.txt")


class AppEnv(str, Enum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


def find_repository_root() -> Path:
    """Locate repository root using marker files, independent of process CWD."""
    start = Path(__file__).resolve().parent
    for candidate in (start, *start.parents):
        if all((candidate / marker).is_file() for marker in _REPO_ROOT_MARKERS):
            return candidate
    msg = "Repository root not found (expected .env.example and requirements.txt)"
    raise FileNotFoundError(msg)


def repository_env_file() -> Path | None:
    """Return repository-root .env when present; otherwise rely on process environment."""
    env_path = find_repository_root() / ".env"
    return env_path if env_path.is_file() else None


def shared_settings_config() -> SettingsConfigDict:
    """
    Shared Pydantic Settings config.

    Uses extra='ignore' so a single repository-level .env may contain variables for
    multiple services without causing validation failures in any one service.

    The repository-root .env path is resolved at instantiation time via
    settings_customise_sources(), not at class definition time.
    """
    return SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )


class SharedSettings(BaseSettings):
    """Configuration shared across all backend services."""

    model_config = shared_settings_config()

    app_name: str = "mannerai-meetings"
    app_env: AppEnv = AppEnv.DEVELOPMENT
    log_level: str = "INFO"

    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/mannerai_meetings"
    )
    database_pool_size: int = Field(default=10, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    database_pool_timeout: int = Field(default=30, ge=1)
    database_pool_recycle: int = Field(default=1800, ge=0)
    database_echo: bool = False

    redis_url: str = "redis://localhost:6379/0"

    # Non-secret conventions for Gateway-issued service-to-service assertions.
    # Signing and verification keys are intentionally service-specific.
    internal_principal_algorithm: Literal["RS256"] = "RS256"
    internal_principal_issuer: str = "gateway-service"
    internal_principal_expire_seconds: int = Field(default=60, ge=1, le=300)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        valid_levels = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
        if normalized not in valid_levels:
            msg = f"Invalid LOG_LEVEL: {value!r}"
            raise ValueError(msg)
        return normalized

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources: list[PydanticBaseSettingsSource] = [
            init_settings,
            env_settings,
        ]
        env_path = repository_env_file()
        if env_path is not None:
            sources.append(
                DotEnvSettingsSource(
                    settings_cls,
                    env_file=env_path,
                    env_file_encoding="utf-8",
                )
            )
        sources.append(file_secret_settings)
        return tuple(sources)


@lru_cache
def get_base_settings() -> SharedSettings:
    """Return cached shared base settings."""
    return SharedSettings()


TSettings = TypeVar("TSettings", bound=BaseSettings)


def cached_settings_factory(settings_cls: type[TSettings]):
    """Build a cached get_settings() factory for a settings class."""

    @lru_cache
    def get_settings() -> TSettings:
        return settings_cls()

    return get_settings
