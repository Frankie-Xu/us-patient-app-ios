import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from services.ai.golden_set import load_golden_set, synthetic_golden_set
from services.ai.regression_cli import main
from services.ai.regression_report import (
    REPORT_SCHEMA,
    REPORT_SCHEMA_VERSION,
    GoldenSetRegressionReport,
    generate_regression_report,
    generate_regression_report_from_json,
)
from services.ai.schema import GoldenSet


FIXTURE = Path(__file__).parents[1] / "fixtures" / "synthetic_golden_set.json"
REPORT_SCHEMA_FILE = Path(__file__).parents[1] / "regression_report.schema.json"


class RegressionReportTests(unittest.TestCase):
    def test_report_is_deterministic_and_contains_gate_fields(self) -> None:
        golden_set = synthetic_golden_set()
        first = generate_regression_report(golden_set)
        second = generate_regression_report(golden_set)

        self.assertEqual(first.to_json(), second.to_json())
        self.assertEqual(first.api_version, "0.2.0")
        self.assertEqual(first.report_schema, REPORT_SCHEMA)
        self.assertEqual(first.schema_version, REPORT_SCHEMA_VERSION)
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

    def test_report_rejects_unknown_fields_and_version_drift(self) -> None:
        report = generate_regression_report(synthetic_golden_set()).to_dict()
        report["new_field"] = "drift"
        with self.assertRaises(ValueError):
            GoldenSetRegressionReport.from_dict(report)

        for field_name, value in (
            ("report_schema", "patient-app-ai/other-report"),
            ("schema_version", "2.0.0"),
            ("api_version", "0.3.0"),
        ):
            payload = generate_regression_report(synthetic_golden_set()).to_dict()
            payload[field_name] = value
            with self.assertRaises(ValueError):
                GoldenSetRegressionReport.from_dict(payload)

    def test_checked_in_report_contract_freezes_required_fields(self) -> None:
        contract = json.loads(REPORT_SCHEMA_FILE.read_text(encoding="utf-8"))

        self.assertFalse(contract["additionalProperties"])
        self.assertEqual(contract["properties"]["report_schema"]["const"], REPORT_SCHEMA)
        self.assertEqual(contract["properties"]["schema_version"]["const"], REPORT_SCHEMA_VERSION)
        self.assertEqual(contract["properties"]["api_version"]["const"], "0.2.0")
        self.assertTrue(set(contract["required"]) >= {"metrics", "error_categories", "delivery_blocked"})

    def test_report_json_rejects_non_object(self) -> None:
        with self.assertRaises(ValueError):
            GoldenSetRegressionReport.from_json("[]")


if __name__ == "__main__":
    unittest.main()
