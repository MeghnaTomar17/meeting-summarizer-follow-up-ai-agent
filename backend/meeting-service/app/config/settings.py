"""Meeting service configuration."""

from shared.config.base import SharedSettings, cached_settings_factory

Settings = SharedSettings

get_settings = cached_settings_factory(SharedSettings)

__all__ = ["Settings", "get_settings"]
