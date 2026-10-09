"""Provider evidence must retain status metadata without secret material."""
from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class OCRProviderEvidenceTests(unittest.TestCase):
    def test_success_and_failure_states_are_explicit_and_redacted(self) -> None:
        report = json.loads((ROOT / "artifacts/staging/ocr-provider-connectivity.json").read_text(encoding="utf-8"))
        self.assertEqual(report["success"]["status"], "success")
        self.assertEqual(report["success"]["model"], "qwen-vl-ocr")
        self.assertGreater(report["success"]["elapsed_ms"], 0)
        self.assertTrue(report["success"]["synthetic_marker_detected"])
        self.assertEqual(report["model_missing"]["status"], "failed")
        self.assertEqual(report["model_missing"]["error_code"], "OCR_PROVIDER_REJECTED")
        self.assertFalse(report["model_missing"]["retryable"])
        serialized = json.dumps(report, sort_keys=True)
        self.assertNotIn("Bearer ", serialized)
        self.assertNotIn("DASHSCOPE_API_KEY", serialized)
        self.assertNotIn("SYNTHETIC OCR TEST", serialized)
        self.assertTrue(report["phi_used"] is False)


if __name__ == "__main__":
    unittest.main()
