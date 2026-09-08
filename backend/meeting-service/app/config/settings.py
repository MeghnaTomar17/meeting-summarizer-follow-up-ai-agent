"""Meeting service configuration."""

from __future__ import annotations

from cryptography.hazmat.primitives.serialization import load_pem_public_key
from pydantic import Field, model_validator

from shared.config.base import AppEnv, SharedSettings, cached_settings_factory

_DEV_INTERNAL_PRINCIPAL_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAukQRnwX8isBsAONNUGF2
/uvWz4PaAfma2PaX8vQDRJhXrQwDHJjs9vYdV+0nOmS5TDLpA0p1VMxiIcUrDloZ
A1bB6Hk4Vc0IzTXclMOomE02pmGrX0hVE01QJopGXYxitk5k7q0cMerCKd0LDkP6
O6WT88rVs+SSVXSdCIaN/aj5EiD0sgpvHfA8AgZsK/zlSkcFDsyjIczS+w634fEn
84BG3KvPSnyZZA9Uwf4kk469P/kbvrt6beY0vyduPCJCWkSvtBd3R/M2omVYvtN4
QIgLpf6C+n5BY00o1o7j0UHpB2Eenj0eEaVjwqHCcqdtNxxBX0lPK80/3tNtWiQz
CQIDAQAB
-----END PUBLIC KEY-----"""


class MeetingSettings(SharedSettings):
    """Meeting service settings."""

    service_name: str = "meeting-service"
    internal_principal_public_key: str = Field(
        default=_DEV_INTERNAL_PRINCIPAL_PUBLIC_KEY
    )

    @model_validator(mode="after")
    def validate_production_internal_principal_public_key(self) -> MeetingSettings:
        if self.app_env != AppEnv.PRODUCTION:
            return self

        public_key = self.internal_principal_public_key
        if public_key == _DEV_INTERNAL_PRINCIPAL_PUBLIC_KEY:
            msg = "INTERNAL_PRINCIPAL_PUBLIC_KEY must not use the development key in production"
            raise ValueError(msg)
        try:
            load_pem_public_key(public_key.encode())
        except (TypeError, ValueError) as error:
            msg = "INTERNAL_PRINCIPAL_PUBLIC_KEY must be a valid PEM public key"
            raise ValueError(msg) from error
        return self


Settings = MeetingSettings

get_settings = cached_settings_factory(MeetingSettings)

__all__ = ["MeetingSettings", "Settings", "get_settings"]
