import unittest
from dataclasses import replace

from services.ai.mock_predictions import MockPredictionVariant, fixed_mock_predictions
from services.ai.output_evaluator import ErrorCategory, evaluate_extraction_output
from services.ai.pipeline import DeterministicStubPipeline
from services.ai.schema import SourceSpan
from services.ai.golden_set import synthetic_golden_set


class OutputEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = synthetic_golden_set().cases[0]
        self.predictions = fixed_mock_predictions(self.case)

    def test_perfect_prediction_has_complete_metrics_and_api_review_state(self) -> None:
        result = evaluate_extraction_output(self.case, self.predictions[MockPredictionVariant.PERFECT])

        self.assertEqual(result.metrics.field_value_accuracy, 1.0)
        self.assertEqual(result.metrics.source_span_accuracy, 1.0)
        self.assertEqual(result.metrics.confidence_mae, 0.0)
        self.assertEqual(result.metrics.review_required_recall, 1.0)
        self.assertFalse(result.delivery_blocked)
        self.assertTrue(all(item.review_required for item in result.review_decisions))
        self.assertTrue(all(item.review_status.value == "needs_review" for item in result.review_decisions))

    def test_field_value_mismatch_is_classified_and_blocks(self) -> None:
        result = evaluate_extraction_output(self.case, self.predictions[MockPredictionVariant.FIELD_VALUE_MISMATCH])

        self.assertIn(ErrorCategory.FIELD_VALUE_MISMATCH, {item.category for item in result.errors})
        self.assertLess(result.metrics.field_value_accuracy, 1.0)
        self.assertTrue(result.delivery_blocked)

    def test_source_span_mismatch_is_classified(self) -> None:
        result = evaluate_extraction_output(self.case, self.predictions[MockPredictionVariant.SOURCE_SPAN_MISMATCH])

        self.assertIn(ErrorCategory.SOURCE_SPAN_MISMATCH, {item.category for item in result.errors})
        self.assertLess(result.metrics.source_span_accuracy, 1.0)
        self.assertTrue(result.delivery_blocked)

    def test_low_confidence_is_measured_without_being_silently_accepted(self) -> None:
        result = evaluate_extraction_output(self.case, self.predictions[MockPredictionVariant.LOW_CONFIDENCE])

        self.assertIn(ErrorCategory.CONFIDENCE_MISMATCH, {item.category for item in result.errors})
        self.assertGreater(result.metrics.confidence_mae, 0.0)
        self.assertFalse(result.delivery_blocked)

    def test_missing_review_required_is_blocking_and_downgraded_for_api(self) -> None:
        result = evaluate_extraction_output(self.case, self.predictions[MockPredictionVariant.REVIEW_REQUIRED_MISSING])

        self.assertIn(ErrorCategory.REVIEW_REQUIRED_MISSING, {item.category for item in result.errors})
        first = next(item for item in result.review_decisions if item.claim_id == self.case.expected_claims[0].claim_id)
        self.assertEqual(first.review_status.value, "needs_review")
        self.assertTrue(first.review_required)
        self.assertTrue(result.delivery_blocked)

    def test_missing_and_unexpected_claims_are_separate_categories(self) -> None:
        missing = evaluate_extraction_output(self.case, self.predictions[MockPredictionVariant.MISSING_CLAIM])
        unexpected = evaluate_extraction_output(self.case, self.predictions[MockPredictionVariant.UNEXPECTED_CLAIM])

        self.assertIn(ErrorCategory.MISSING_CLAIM, {item.category for item in missing.errors})
        self.assertIn(ErrorCategory.UNEXPECTED_CLAIM, {item.category for item in unexpected.errors})
        self.assertTrue(missing.delivery_blocked)
        self.assertTrue(unexpected.delivery_blocked)

    def test_unresolved_span_is_a_distinct_blocker(self) -> None:
        claim = self.predictions[MockPredictionVariant.PERFECT][0]
        predictions = (replace(claim, source_span=SourceSpan(start=0, end=999, page=1)), self.predictions[MockPredictionVariant.PERFECT][1])
        blocks = DeterministicStubPipeline().ocr_layout(self.case).blocks
        result = evaluate_extraction_output(self.case, predictions, ocr_blocks=blocks)

        self.assertIn(ErrorCategory.SOURCE_SPAN_UNRESOLVED, {item.category for item in result.errors})
        self.assertTrue(result.delivery_blocked)

    def test_invalid_tolerance_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_extraction_output(self.case, self.predictions[MockPredictionVariant.PERFECT], confidence_tolerance=-0.1)

    def test_duplicate_prediction_ids_are_rejected(self) -> None:
        claim = self.predictions[MockPredictionVariant.PERFECT][0]
        with self.assertRaises(ValueError):
            evaluate_extraction_output(self.case, (claim, claim))


if __name__ == "__main__":
    unittest.main()
