"""Compose must expose provider egress only through local configuration."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ComposeEgressTests(unittest.TestCase):
    def test_worker_uses_opt_in_proxy_and_local_no_proxy_boundaries(self) -> None:
        compose = (ROOT / "infra/staging/compose.yaml").read_text(encoding="utf-8")
        self.assertIn("HTTP_PROXY: ${STAGING_HTTP_PROXY:-}", compose)
        self.assertIn("HTTPS_PROXY: ${STAGING_HTTPS_PROXY:-}", compose)
        self.assertIn("ALL_PROXY: ${STAGING_ALL_PROXY:-}", compose)
        self.assertIn("NO_PROXY: ${STAGING_NO_PROXY:-localhost,127.0.0.1,postgres,localstack,redis,api,worker}", compose)
        self.assertIn('"host.docker.internal:host-gateway"', compose)

    def test_tracked_example_has_no_proxy_address_or_provider_key(self) -> None:
        example = (ROOT / ".env.staging.example").read_text(encoding="utf-8")
        self.assertIn("STAGING_HTTP_PROXY=", example)
        self.assertIn("STAGING_HTTPS_PROXY=", example)
        self.assertNotIn("host.docker.internal:", example)
        self.assertNotIn("DASHSCOPE_API_KEY=sk-", example)


if __name__ == "__main__":
    unittest.main()
