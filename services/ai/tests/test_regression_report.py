import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from services.ai.golden_set import load_golden_set, synthetic_golden_set
from services.ai.regression_cli import main
from services.ai.regression_report import GoldenSetRegressionReport, generate_regression_report, generate_regression_report_from_json
from services.ai.schema import GoldenSet


FIXTURE = Path(__file__).parents[1] / "fixtures" / "synthetic_golden_set.json"


class RegressionReportTests(unittest.TestCase):
    def test_report_is_deterministic_and_contains_gate_fields(self) -> None:
        golden_set = synthetic_golden_set()
        first = generate_regression_report(golden_set)
        second = generate_regression_report(golden_set)

        self.assertEqual(first.to_json(), second.to_json())
        self.assertEqual(first.api_version, "0.2.0")
        self.assertEqual(first.dataset_id, golden_set.dataset_id)
        self.assertEqual(first.sample_count, 2)
        self.assertIn("precision", first.metrics)
        self.assertIn("regression.conflict", first.error_categories)
        self.assertTrue(first.delivery_blocked)

    def test_report_round_trips_json(self) -> None:
        report = generate_regression_report(synthetic_golden_set())
        restored = GoldenSetRegressionReport.from_json(report.to_json())

        self.assertEqual(restored.to_dict(), report.to_dict())

    def test_clean_single_case_is_not_blocked(self) -> None:
        golden_set = synthetic_golden_set()
        clean_set = GoldenSet(
            dataset_id=golden_set.dataset_id,
            version=golden_set.version,
            data_classification=golden_set.data_classification,
            cases=(golden_set.cases[0],),
        )

        report = generate_regression_report(clean_set)

        self.assertFalse(report.delivery_blocked)
        self.assertEqual(report.sample_count, 1)
        self.assertEqual(report.error_categories, {})

    def test_report_from_fixture_preserves_dataset_identity(self) -> None:
        report = generate_regression_report_from_json(str(FIXTURE))

        self.assertEqual(report.dataset_id, "patient-app-ai-synthetic")
        self.assertEqual(report.dataset_version, "1.0.0")
        self.assertEqual(report.sample_count, 2)

    def test_cli_emits_parseable_report_json(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(["--golden-set", str(FIXTURE)])
        payload = json.loads(output.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["api_version"], "0.2.0")
        self.assertEqual(payload["sample_count"], 2)
        self.assertIn("delivery_blocked", payload)

    def test_report_rejects_missing_fields_and_invalid_gate_values(self) -> None:
        report = generate_regression_report(synthetic_golden_set()).to_dict()
        del report["delivery_blocked"]
        with self.assertRaises(ValueError):
            GoldenSetRegressionReport.from_dict(report)

        report = generate_regression_report(synthetic_golden_set()).to_dict()
        report["sample_count"] = 0
        with self.assertRaises(ValueError):
            GoldenSetRegressionReport.from_dict(report)

    def test_report_json_rejects_non_object(self) -> None:
        with self.assertRaises(ValueError):
            GoldenSetRegressionReport.from_json("[]")


if __name__ == "__main__":
    unittest.main()
