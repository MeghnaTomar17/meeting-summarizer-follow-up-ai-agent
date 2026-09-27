"""Gateway service configuration."""

from __future__ import annotations

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from pydantic import Field, SecretStr, model_validator

from shared.config.base import AppEnv, SharedSettings, cached_settings_factory

_DEV_JWT_SECRET = "dev-only-jwt-secret-not-for-production-use"
_DEV_INTERNAL_PRINCIPAL_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC6RBGfBfyKwGwA
401QYXb+69bPg9oB+ZrY9pfy9ANEmFetDAMcmOz29h1X7Sc6ZLlMMukDSnVUzGIh
xSsOWhkDVsHoeThVzQjNNdyUw6iYTTamYatfSFUTTVAmikZdjGK2TmTurRwx6sIp
3QsOQ/o7pZPzytWz5JJVdJ0Iho39qPkSIPSyCm8d8DwCBmwr/OVKRwUOzKMhzNL7
Drfh8SfzgEbcq89KfJlkD1TB/iSTjr0/+Ru+u3pt5jS/J248IkJaRK+0F3dH8zai
ZVi+03hAiAul/oL6fkFjTSjWjuPRQekHYR6ePR4RpWPCocJyp203HEFfSU8rzT/e
021aJDMJAgMBAAECggEAB+Oy8t9CKn7avEFkcJGGRKco3LaHHQMNZN/yAO2Gt2iz
+v2JorQUAmRbixI9kX67bf+wiK4GUPqMtAU5zQRyL4bk1PPQd+rksutzfb4ZVaUc
mdjEdVdXGieRy+Yas6Lq+fGRWx4sNe2NfpAxJBArSMw7O23llhZp/9JeBeLMIBit
48wfmo02qRruYIyK8WW3e2IhID5orhOxFfTnI4WBqTL18DooiAFg2vAl80iw09Qh
UiLMAq/rckyyiuFas5BTqDEjb3AmW7ZMNMY/SRdot9PsgD9HGVQwkx+iNb+p5a2o
OJtann78HlWySaLzOsWk+r2F5djkfzNqFRc8L9wdwQKBgQDzRYt2OnIGYUnTUDxT
fRxr4YRPD7W8VG6clDCT8raACsKG3mhu8FhoQKNJHdmmgmKs8fiEks7R2mTfdF8u
ef9CCNtNxi5/5nUlSzmWuM/az6o0IXUXENd78h7sLxWOrK0FrfwYWZ6j60K04kHq
s/KEN/wNv1gQRjBYSQPMuOFUyQKBgQDEAviqha0d4UQFHkwhv+OKT7knSAAMfPv6
1cRjyG+WMeLSkgTTQjTOErHbcBHOlnBCrhxtrDC09cF3ROmabsyIfs3n1JBY3KdV
Z/W4m8oni9oQoltY4cBTcsxhZJbXkpNmEwKISC7gZV4v/ibuK1WKKs4EoD/4+Lv+
B4/mELJMQQKBgQC9HxKljhg5F4cyLU1IxpnC0KZwZFEvoSAAwD/ntKfmcPb7rInZ
vSWtnpqSbA9ZoEGgG9jND+iTQkprYWfhlNw5dPMwymI58mqd3JZfszt76zdxoZUK
ooAzDm61xIDo0xsLsE+sineHDY1lXARMtypRWcis01VeCYLqD5FRpWUf6QKBgDO0
tPQGn0wqiE7xVxPwEo4Byc3a6Ghi7/WTPmM0FHuCXVs+uZcg990EgXZpcckVVjfA
xi8IJTEXQxm7TAQ5Bitbh+WH5SwLyPh2nBM+xWz5L2UD7yTbKGja958ZcdEcEVXz
3c8le3gmRVpTqOFa/Q2djQsbWsTKmIzCYetGrEIBAoGAT0C6CrQfM2zGpuioA4eI
7BNc7WFoti2l0jlWTGuYsXytd+Jn4B5fh3D64nx7Zh+gxKf9kaJDMXNScvttCziz
I/Km9yfHm6Yhv0ttmFwaOgPQ8JBwm80X0taDuA1PMywyB0VkmxlAm9jSb6l5F9rV
6mLDbD8+0TdKvjgcWA37Wmc=
-----END PRIVATE KEY-----"""

_INSECURE_JWT_SECRETS = frozenset(
    {
        "change-me",
        "change-me-use-a-long-random-string",
        _DEV_JWT_SECRET,
    }
)


class GatewaySettings(SharedSettings):
    """Gateway-specific settings (auth + downstream service URLs)."""

    service_name: str = "gateway-service"
    jwt_secret: SecretStr = Field(default=SecretStr(_DEV_JWT_SECRET))
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    refresh_token_expire_seconds: int = Field(default=2_592_000, ge=60, le=31_536_000)
    internal_principal_private_key: SecretStr = Field(
        default=SecretStr(_DEV_INTERNAL_PRINCIPAL_PRIVATE_KEY)
    )

    meeting_service_url: str = "http://localhost:8001"
    ai_service_url: str = "http://localhost:8002"
    search_service_url: str = "http://localhost:8003"

    @model_validator(mode="after")
    def validate_production_jwt_secret(self) -> GatewaySettings:
        if self.app_env != AppEnv.PRODUCTION:
            return self

        secret = self.jwt_secret.get_secret_value()
        if secret in _INSECURE_JWT_SECRETS or len(secret) < 32:
            msg = "JWT_SECRET must be a strong secret (min 32 characters) in production"
            raise ValueError(msg)
        private_key = self.internal_principal_private_key.get_secret_value()
        if private_key == _DEV_INTERNAL_PRINCIPAL_PRIVATE_KEY:
            msg = "INTERNAL_PRINCIPAL_PRIVATE_KEY must not use the development key in production"
            raise ValueError(msg)
        try:
            load_pem_private_key(private_key.encode(), password=None)
        except (TypeError, ValueError) as error:
            msg = "INTERNAL_PRINCIPAL_PRIVATE_KEY must be a valid unencrypted PEM private key"
            raise ValueError(msg) from error
        return self


get_settings = cached_settings_factory(GatewaySettings)

__all__ = ["GatewaySettings", "get_settings"]
