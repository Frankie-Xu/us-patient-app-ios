"""Regression checks for the HTTP staging acceptance command."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load_module():
    import importlib.util
    import sys

    module_path = ROOT / "scripts/staging/integration_smoke.py"
    spec = importlib.util.spec_from_file_location("integration_smoke_test_module", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError("integration_smoke.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class IntegrationSmokeScriptTests(unittest.TestCase):
    def test_processing_failure_is_a_blocker(self) -> None:
        module = _load_module()
        report = module._base_report()
        module._record_processing_stage(
            report,
            verification="live_http+provider_worker",
            processing_state="failed",
            queue="enqueued",
            ocr_provider="provider",
            input_media_type="image/png",
        )
        self.assertEqual(report["stages"]["processing"]["status"], "failed")
        self.assertFalse(report["stages"]["processing"]["worker_completed"])
        self.assertEqual(report["blockers"], [{"code": "ocr_processing_failed"}])
        self.assertEqual(report["not_validated"], [{"stage": "processing", "reason": "ocr_processing_failed"}])

    def test_dry_run_has_route_gaps_and_no_credentials(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "report.json"
            self.assertEqual(module.main(["--dry-run", "--artifact", str(artifact)]), 0)
            report = json.loads(artifact.read_text(encoding="utf-8"))
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(report["status"], "dry_run")
        self.assertIn("doctor_brief", report["route_gaps"])
        self.assertIn("implemented", report)
        self.assertEqual(report["live"], {})
        self.assertEqual(report["mock"], {})
        self.assertEqual(report["authentication"]["status"], "not_run")
        serialized = json.dumps(report, sort_keys=True)
        self.assertNotIn("Bearer ", serialized)
        self.assertNotIn("synthetic-token", serialized)

    def test_auth_header_is_not_written_to_report(self) -> None:
        import os

        module = _load_module()
        previous = os.environ.get("STAGING_AUTH_TOKEN")
        try:
            os.environ["STAGING_AUTH_TOKEN"] = "Bearer synthetic-token-never-logged"
            header, mode = module._auth_header()
            self.assertEqual(mode, "provided_token_unverified")
            self.assertIn("synthetic-token", header)
            report = module._base_report()
            self.assertNotIn(header, json.dumps(report))
        finally:
            if previous is None:
                os.environ.pop("STAGING_AUTH_TOKEN", None)
            else:
                os.environ["STAGING_AUTH_TOKEN"] = previous


if __name__ == "__main__":
    unittest.main()
