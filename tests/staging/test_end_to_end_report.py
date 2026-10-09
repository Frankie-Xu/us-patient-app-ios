"""The checked-in staging report must distinguish live and fixture stages."""
from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class EndToEndReportTests(unittest.TestCase):
    def test_live_flow_is_passed_and_mock_boundaries_are_explicit(self) -> None:
        report = json.loads((ROOT / "artifacts/staging/integration-acceptance-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["blockers"], [])
        for stage in ("upload", "upload_content", "processing", "facts", "fact_review", "share", "retention"):
            self.assertEqual(report["stages"][stage]["status"], "passed", stage)
        self.assertEqual(report["stages"]["processing"]["verification"], "live_http+provider_worker")
        not_validated = {item["stage"]: item["reason"] for item in report["not_validated"]}
        self.assertIn("doctor_brief", not_validated)
        self.assertIn("visit_questions", not_validated)
        self.assertIn("pdf_export", not_validated)


if __name__ == "__main__":
    unittest.main()
