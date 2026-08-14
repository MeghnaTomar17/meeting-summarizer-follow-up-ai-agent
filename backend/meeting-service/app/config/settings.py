"""Meeting service configuration."""

from shared.config.base import SharedSettings, cached_settings_factory


class MeetingSettings(SharedSettings):
    """Meeting service settings."""

    service_name: str = "meeting-service"


Settings = MeetingSettings

get_settings = cached_settings_factory(MeetingSettings)

__all__ = ["MeetingSettings", "Settings", "get_settings"]
