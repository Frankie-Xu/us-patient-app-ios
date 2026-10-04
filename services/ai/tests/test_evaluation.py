import unittest

from services.ai.golden_set import golden_set_from_dict, synthetic_golden_set
from services.ai.pipeline import DeterministicStubPipeline
from services.ai.reporting import evaluate_golden_set
from services.ai.schema import Claim, GoldenCase


class EvaluationBoundaryTests(unittest.TestCase):
    def test_synthetic_fixture_round_trips_and_runs_deterministically(self) -> None:
        golden_set = synthetic_golden_set()
        restored = golden_set_from_dict(golden_set.to_dict())
        first = evaluate_golden_set(restored)
        second = evaluate_golden_set(restored)

        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.metrics["precision"], 1.0)
        self.assertEqual(first.metrics["recall"], 1.0)
        self.assertEqual(first.metrics["citation_coverage"], 1.0)
        self.assertTrue(first.delivery_blocked)
        self.assertTrue(first.blocking_errors)

    def test_required_claim_metadata_is_enforced(self) -> None:
        with self.assertRaises(ValueError):
            Claim(
                claim_id="claim-1",
                text_en="Synthetic fact",
                text_zh="合成事实",
                source_ref="",
                source_type="synthetic_note",
                confidence=0.5,
                review_status="needs_review",
            )

        payload = synthetic_golden_set().to_dict()
        del payload["cases"][0]["expected_claims"][0]["source_span"]
        with self.assertRaises(ValueError):
            golden_set_from_dict(payload)
        with self.assertRaises(ValueError):
            Claim(
                claim_id="claim-1",
                text_en="Synthetic fact",
                text_zh="合成事实",
                source_ref="synthetic:note:1",
                source_type="synthetic_note",
                confidence=1.1,
                review_status="needs_review",
            )

    def test_invalid_fact_line_is_a_high_severity_blocker(self) -> None:
        case = GoldenCase(
            case_id="invalid-line",
            document_source_ref="synthetic:invalid",
            document_source_type="synthetic_note",
            document_text="FACT\t{not-json}",
            expected_claims=(),
        )
        report = evaluate_golden_set(
            golden_set_from_dict(
                {
                    "dataset_id": "test",
                    "version": "1",
                    "data_classification": "synthetic",
                    "cases": [
                        {
                            "case_id": case.case_id,
                            "document": {
                                "source_ref": case.document_source_ref,
                                "source_type": case.document_source_type,
                                "text": case.document_text,
                            },
                            "expected_claims": [],
                            "expected_conflicts": [],
                        }
                    ],
                }
            ),
            DeterministicStubPipeline(),
        )
        self.assertTrue(report.delivery_blocked)
        self.assertTrue(any(error.severity.value == "high" for error in report.blocking_errors))

    def test_bilingual_text_is_part_of_the_regression_match(self) -> None:
        payload = synthetic_golden_set().to_dict()
        document = payload["cases"][0]["document"]["text"]
        payload["cases"][0]["document"]["text"] = document.replace("listed as active", "listed as inactive", 1)
        report = evaluate_golden_set(golden_set_from_dict(payload))

        first_case = report.cases[0]
        self.assertLess(first_case.precision, 1.0)
        self.assertLess(first_case.recall, 1.0)
        self.assertEqual(first_case.citation_coverage, 1.0)
        self.assertTrue(first_case.delivery_blocked)


if __name__ == "__main__":
    unittest.main()
