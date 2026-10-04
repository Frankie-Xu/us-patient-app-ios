import json
import unittest
from dataclasses import replace
from pathlib import Path

from services.ai.api_projection import ApiProjection, project_evaluation
from services.ai.golden_set import synthetic_golden_set
from services.ai.mock_predictions import MockPredictionVariant, fixed_mock_predictions
from services.ai.output_evaluator import ErrorCategory, evaluate_extraction_output
from services.ai.pipeline import DeterministicStubPipeline
from services.ai.route_compatibility import (
    RouteCompatibilityError,
    projection_to_route_payload,
    validate_route_json,
    validate_route_payload,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "api_v0_2_projection.json"


class RouteCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = synthetic_golden_set().cases[0]
        self.predictions = fixed_mock_predictions(self.case)[MockPredictionVariant.PERFECT]
        evaluation = evaluate_extraction_output(self.case, self.predictions)
        self.payload = projection_to_route_payload(project_evaluation(evaluation, self.predictions))

    def test_checked_in_fixture_is_consumable_as_http_json(self) -> None:
        report = validate_route_json(FIXTURE.read_text(encoding="utf-8"))

        self.assertEqual(report.api_version, "0.2.0")
        self.assertEqual(report.fact_create_count, 2)
        self.assertEqual(report.fact_review_count, 2)
        self.assertEqual(set(report.claim_ids), {"synthetic-medication-001", "synthetic-medication-002"})

    def test_projection_payload_round_trips_through_route_parser(self) -> None:
        report = validate_route_payload(self.payload)
        restored = ApiProjection.from_dict(self.payload)

        self.assertEqual(report.fact_create_count, len(restored.fact_creates))
        self.assertEqual(report.fact_review_count, len(restored.fact_reviews))
        self.assertEqual(restored.to_dict(), self.payload)

    def test_required_route_fields_are_checked(self) -> None:
        missing = json.loads(json.dumps(self.payload))
        del missing["fact_creates"][0]["source_ref"]
        with self.assertRaises(RouteCompatibilityError):
            validate_route_payload(missing)

        wrong_version = json.loads(json.dumps(self.payload))
        wrong_version["api_version"] = "0.1.0"
        with self.assertRaises(RouteCompatibilityError):
            validate_route_payload(wrong_version)

    def test_unknown_route_fields_are_rejected(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        payload["fact_reviews"][0]["unexpected"] = "drift"

        with self.assertRaises(RouteCompatibilityError):
            validate_route_payload(payload)

    def test_low_confidence_route_payload_requires_category_and_review(self) -> None:
        predictions = fixed_mock_predictions(self.case)[MockPredictionVariant.LOW_CONFIDENCE]
        evaluation = evaluate_extraction_output(self.case, predictions)
        payload = projection_to_route_payload(project_evaluation(evaluation, predictions))
        fact = payload["fact_creates"][0]

        self.assertIn(ErrorCategory.LOW_CONFIDENCE.value, fact["error_categories"])
        self.assertTrue(fact["review_required"])
        self.assertEqual(fact["review_status"], "needs_review")
        validate_route_payload(payload)

        fact["error_categories"].remove(ErrorCategory.LOW_CONFIDENCE.value)
        with self.assertRaises(RouteCompatibilityError):
            validate_route_payload(payload)

    def test_missing_span_route_payload_requires_category_and_review(self) -> None:
        predictions = fixed_mock_predictions(self.case)[MockPredictionVariant.PERFECT]
        predictions = (replace(predictions[0], source_span=None), predictions[1])
        evaluation = evaluate_extraction_output(self.case, predictions)
        payload = projection_to_route_payload(project_evaluation(evaluation, predictions))
        fact = payload["fact_creates"][0]

        self.assertIsNone(fact["source_span"])
        self.assertIn(ErrorCategory.SOURCE_SPAN_MISSING.value, fact["error_categories"])
        validate_route_payload(payload)

        fact["error_categories"].remove(ErrorCategory.SOURCE_SPAN_MISSING.value)
        with self.assertRaises(RouteCompatibilityError):
            validate_route_payload(payload)

    def test_conflict_route_payload_cannot_be_confirmed(self) -> None:
        case = synthetic_golden_set().cases[1]
        predictions = fixed_mock_predictions(case)[MockPredictionVariant.PERFECT]
        evaluation = evaluate_extraction_output(case, predictions)
        conflicts = DeterministicStubPipeline().run(case).conflicts.conflicts
        payload = projection_to_route_payload(project_evaluation(evaluation, predictions, conflicts=conflicts))

        self.assertTrue(all(ErrorCategory.CONFLICT_DETECTED.value in fact["error_categories"] for fact in payload["fact_creates"]))
        self.assertTrue(all(fact["review_status"] == "needs_review" for fact in payload["fact_creates"]))
        validate_route_payload(payload)

        payload["fact_creates"][0]["review_status"] = "confirmed"
        with self.assertRaises(RouteCompatibilityError):
            validate_route_payload(payload)

    def test_missing_review_for_created_fact_is_rejected(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        payload["fact_reviews"] = payload["fact_reviews"][1:]

        with self.assertRaises(RouteCompatibilityError):
            validate_route_payload(payload)


if __name__ == "__main__":
    unittest.main()
