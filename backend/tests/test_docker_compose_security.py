"""Security invariants for service-specific internal-principal key injection."""

from __future__ import annotations

import unittest
from pathlib import Path
from re import search


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPOSITORY_ROOT / "docker-compose.yml"


def _service_block(compose: str, service_name: str) -> str:
    """Return one top-level Compose service block without requiring a YAML dependency."""
    marker = f"  {service_name}:\n"
    start = compose.index(marker)
    following = search(r"\n  (?! )[A-Za-z0-9_-]+:\n", compose[start + len(marker) :])
    end = len(compose) if following is None else start + len(marker) + following.start()
    return compose[start:end]


class DockerComposeSecurityTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.compose = COMPOSE_FILE.read_text(encoding="utf-8")

    def test_internal_principal_key_distribution_is_service_specific(self) -> None:
        gateway = _service_block(self.compose, "gateway-service")
        meeting = _service_block(self.compose, "meeting-service")

        self.assertIn("INTERNAL_PRINCIPAL_PRIVATE_KEY:", gateway)
        self.assertIn("INTERNAL_PRINCIPAL_PUBLIC_KEY:", meeting)
        self.assertNotIn("INTERNAL_PRINCIPAL_PRIVATE_KEY:", meeting)
        self.assertNotIn("env_file:", meeting)
        self.assertNotIn("INTERNAL_PRINCIPAL_PRIVATE_KEY:", self.compose.split("services:", 1)[0])

        for service_name in ("ai-service", "search-service", "worker-service"):
            service = _service_block(self.compose, service_name)
            with self.subTest(service=service_name):
                self.assertNotIn("env_file:", service)
                self.assertNotIn("INTERNAL_PRINCIPAL_PRIVATE_KEY:", service)


if __name__ == "__main__":
    unittest.main()
