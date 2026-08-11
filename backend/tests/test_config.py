"""Phase 2.1 configuration management tests."""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from pydantic import SecretStr, ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from shared.config.base import (  # noqa: E402
    AppEnv,
    SharedSettings,
    get_base_settings,
)


def _load_service_settings_module(service_name: str) -> ModuleType:
    """Load a service settings module without colliding on the shared `app` package."""
    service_root = str(BACKEND_ROOT / service_name)
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    if service_root in sys.path:
        sys.path.remove(service_root)
    sys.path.insert(0, service_root)
    return importlib.import_module("app.config.settings")


class ConfigTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._original_env = os.environ.copy()
        get_base_settings.cache_clear()

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._original_env)
        get_base_settings.cache_clear()

    def test_default_development_configuration(self) -> None:
        settings = SharedSettings()
        self.assertEqual(settings.app_name, "mannerai-meetings")
        self.assertEqual(settings.app_env, AppEnv.DEVELOPMENT)
        self.assertEqual(settings.log_level, "INFO")
        self.assertEqual(settings.database_pool_size, 10)
        self.assertFalse(settings.database_echo)

    def test_environment_variable_override(self) -> None:
        os.environ["APP_NAME"] = "override-app"
        os.environ["LOG_LEVEL"] = "debug"
        settings = SharedSettings()
        self.assertEqual(settings.app_name, "override-app")
        self.assertEqual(settings.log_level, "DEBUG")

    def test_type_conversion(self) -> None:
        os.environ["DATABASE_ECHO"] = "true"
        os.environ["DATABASE_POOL_SIZE"] = "25"
        settings = SharedSettings()
        self.assertTrue(settings.database_echo)
        self.assertEqual(settings.database_pool_size, 25)

    def test_cached_settings_behavior(self) -> None:
        first = get_base_settings()
        second = get_base_settings()
        self.assertIs(first, second)

        get_base_settings.cache_clear()
        third = get_base_settings()
        self.assertIsNot(first, third)

    def test_production_insecure_jwt_secret_rejected(self) -> None:
        gateway_module = _load_service_settings_module("gateway-service")
        with self.assertRaises(ValidationError):
            gateway_module.GatewaySettings(
                app_env=AppEnv.PRODUCTION,
                jwt_secret=SecretStr("change-me"),
            )

    def test_production_accepts_strong_jwt_secret(self) -> None:
        gateway_module = _load_service_settings_module("gateway-service")
        strong_secret = "a" * 32
        settings = gateway_module.GatewaySettings(
            app_env=AppEnv.PRODUCTION,
            jwt_secret=SecretStr(strong_secret),
        )
        self.assertEqual(settings.jwt_secret.get_secret_value(), strong_secret)

    def test_service_specific_configuration_isolation(self) -> None:
        gateway_module = _load_service_settings_module("gateway-service")
        ai_module = _load_service_settings_module("ai-service")

        os.environ["JWT_SECRET"] = "gateway-jwt-secret-value-32-chars-min!!"
        os.environ["OPENAI_API_KEY"] = "sk-test-openai-key"

        gateway = gateway_module.GatewaySettings()
        ai = ai_module.AISettings()

        self.assertIn("jwt_secret", gateway_module.GatewaySettings.model_fields)
        self.assertNotIn("jwt_secret", ai_module.AISettings.model_fields)
        self.assertIn("openai_api_key", ai_module.AISettings.model_fields)
        self.assertNotIn("openai_api_key", gateway_module.GatewaySettings.model_fields)

        self.assertEqual(
            gateway.jwt_secret.get_secret_value(),
            "gateway-jwt-secret-value-32-chars-min!!",
        )
        self.assertEqual(ai.openai_api_key.get_secret_value(), "sk-test-openai-key")

    def test_repository_root_env_file_independent_of_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env.example").write_text("# marker\n", encoding="utf-8")
            (root / "requirements.txt").write_text("# test\n", encoding="utf-8")
            (root / ".env").write_text("APP_NAME=from-root-env-file\n", encoding="utf-8")

            original_cwd = Path.cwd()
            with patch("shared.config.base.find_repository_root", return_value=root):
                try:
                    os.chdir(root)
                    settings = SharedSettings()
                finally:
                    os.chdir(original_cwd)

            self.assertEqual(settings.app_name, "from-root-env-file")

    def test_unrelated_env_vars_do_not_break_service_settings(self) -> None:
        gateway_module = _load_service_settings_module("gateway-service")
        os.environ["OPENAI_API_KEY"] = "sk-unrelated"
        os.environ["CELERY_BROKER_URL"] = "redis://localhost:6379/9"
        settings = gateway_module.GatewaySettings()
        self.assertEqual(settings.app_env, AppEnv.DEVELOPMENT)

    def test_cached_service_settings_factory(self) -> None:
        gateway_module = _load_service_settings_module("gateway-service")
        gateway_module.get_settings.cache_clear()
        first = gateway_module.get_settings()
        second = gateway_module.get_settings()
        self.assertIs(first, second)
        self.assertIsInstance(first, gateway_module.GatewaySettings)


if __name__ == "__main__":
    unittest.main()
