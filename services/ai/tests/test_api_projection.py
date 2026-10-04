import unittest
from dataclasses import replace

from services.ai.api_projection import ApiProjection, ApiReviewStatus, FactCreate, FactReview, project_evaluation
from services.ai.golden_set import synthetic_golden_set
from services.ai.mock_predictions import MockPredictionVariant, fixed_mock_predictions
from services.ai.output_evaluator import ErrorCategory, evaluate_extraction_output
from services.ai.pipeline import DeterministicStubPipeline


class ApiProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = synthetic_golden_set().cases[0]
        self.predictions = fixed_mock_predictions(self.case)
        self.evaluation = evaluate_extraction_output(self.case, self.predictions[MockPredictionVariant.PERFECT])

    def test_projection_round_trips_json(self) -> None:
        projection = project_evaluation(self.evaluation, self.predictions[MockPredictionVariant.PERFECT])
        restored = ApiProjection.from_json(projection.to_json())

        self.assertEqual(restored.to_dict(), projection.to_dict())
        self.assertEqual(restored.api_version, "0.2.0")

    def test_fact_create_maps_claim_fields_span_confidence_and_errors(self) -> None:
        projection = project_evaluation(self.evaluation, self.predictions[MockPredictionVariant.PERFECT])
        fact = projection.fact_creates[0]

        self.assertEqual(fact.claim_id, self.case.expected_claims[0].claim_id)
        self.assertEqual(fact.source_ref, self.case.expected_claims[0].source_ref)
        self.assertEqual(fact.source_span, self.case.expected_claims[0].source_span)
        self.assertEqual(fact.confidence, 1.0)
        self.assertEqual(fact.review_status, ApiReviewStatus.NEEDS_REVIEW)
        self.assertTrue(fact.review_required)

    def test_low_confidence_is_review_required_and_never_confirmed(self) -> None:
        predictions = self.predictions[MockPredictionVariant.LOW_CONFIDENCE]
        evaluation = evaluate_extraction_output(self.case, predictions)
        projection = project_evaluation(evaluation, predictions, low_confidence_threshold=0.8)
        fact = projection.fact_creates[0]

        self.assertIn(ErrorCategory.LOW_CONFIDENCE, fact.error_categories)
        self.assertTrue(fact.review_required)
        self.assertEqual(fact.review_status, ApiReviewStatus.NEEDS_REVIEW)

    def test_missing_span_is_projected_as_review_required(self) -> None:
        predictions = self.predictions[MockPredictionVariant.PERFECT]
        predictions = (replace(predictions[0], source_span=None), predictions[1])
        evaluation = evaluate_extraction_output(self.case, predictions)
        projection = project_evaluation(evaluation, predictions)
        fact = projection.fact_creates[0]

        self.assertIsNone(fact.source_span)
        self.assertIn(ErrorCategory.SOURCE_SPAN_MISSING, fact.error_categories)
        self.assertEqual(fact.review_status, ApiReviewStatus.NEEDS_REVIEW)
        self.assertTrue(fact.review_required)

    def test_conflict_marks_every_affected_fact_for_review(self) -> None:
        case = synthetic_golden_set().cases[1]
        predictions = fixed_mock_predictions(case)[MockPredictionVariant.PERFECT]
        evaluation = evaluate_extraction_output(case, predictions)
        pipeline_output = DeterministicStubPipeline().run(case)
        projection = project_evaluation(evaluation, predictions, conflicts=pipeline_output.conflicts.conflicts)

        self.assertEqual(len(projection.fact_creates), 2)
        self.assertTrue(all(ErrorCategory.CONFLICT_DETECTED in fact.error_categories for fact in projection.fact_creates))
        self.assertTrue(all(fact.review_required for fact in projection.fact_creates))
        self.assertTrue(all(fact.review_status == ApiReviewStatus.NEEDS_REVIEW for fact in projection.fact_creates))

    def test_missing_claim_becomes_rejected_review_queue_item(self) -> None:
        predictions = self.predictions[MockPredictionVariant.MISSING_CLAIM]
        evaluation = evaluate_extraction_output(self.case, predictions)
        projection = project_evaluation(evaluation, predictions)

        missing_id = self.case.expected_claims[1].claim_id
        review = next(item for item in projection.fact_reviews if item.claim_id == missing_id)
        self.assertEqual(review.review_status, ApiReviewStatus.REJECTED)
        self.assertTrue(review.review_required)
        self.assertIsNone(review.source_ref)

    def test_projection_rejects_confirmed_status_and_wrong_version(self) -> None:
        projection = project_evaluation(self.evaluation, self.predictions[MockPredictionVariant.PERFECT])
        fact_payload = projection.fact_creates[0].to_dict()
        fact_payload["review_status"] = "confirmed"
        with self.assertRaises(ValueError):
            FactCreate.from_dict(fact_payload)

        review_payload = projection.fact_reviews[0].to_dict()
        review_payload["review_status"] = "confirmed"
        with self.assertRaises(ValueError):
            FactReview.from_dict(review_payload)
        fact_payload["review_status"] = "needs_review"
        fact_payload["api_version"] = "0.1.0"
        with self.assertRaises(ValueError):
            FactCreate.from_dict(fact_payload)

    def test_rejected_input_remains_rejected_without_authorizing_confirmation(self) -> None:
        predictions = self.predictions[MockPredictionVariant.PERFECT]
        predictions = (replace(predictions[0], review_status="rejected"), predictions[1])
        evaluation = evaluate_extraction_output(self.case, predictions)
        projection = project_evaluation(evaluation, predictions)

        self.assertEqual(projection.fact_creates[0].review_status, ApiReviewStatus.REJECTED)
        self.assertTrue(projection.fact_creates[0].review_required)


if __name__ == "__main__":
    unittest.main()
