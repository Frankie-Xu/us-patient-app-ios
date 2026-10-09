"""Worker retry and review-gate evidence remains explicit and PHI-free."""
from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class WorkerFailureEvidenceTests(unittest.TestCase):
    def test_failure_and_review_guards_are_recorded(self) -> None:
        report = json.loads((ROOT / "artifacts/staging/worker-failure-retry.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["retryable_provider_error"]["first_failure"], "queued")
        self.assertFalse(report["terminal_provider_error"]["requeued"])
        self.assertFalse(report["review_gate"]["low_confidence_auto_confirm"])
        self.assertFalse(report["review_gate"]["missing_source_auto_confirm"])
        self.assertFalse(report["review_gate"]["conflict_auto_confirm"])
        self.assertFalse(report["phi_used"])


if __name__ == "__main__":
    unittest.main()
