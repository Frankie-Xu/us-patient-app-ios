import unittest
from dataclasses import replace

from services.ai.doctor_view import (
    GATE_SCHEMA,
    DoctorViewErrorCategory,
    evaluate_doctor_view,
)
from services.ai.golden_set import synthetic_golden_set


class DoctorViewGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = synthetic_golden_set().cases[0]
        self.confirmed = tuple(replace(claim, review_status="confirmed") for claim in self.case.expected_claims)

    def test_only_confirmed_complete_claims_are_included(self) -> None:
        result = evaluate_doctor_view(self.confirmed)

        self.assertEqual(result.gate_schema, GATE_SCHEMA)
        self.assertEqual(result.included_claim_ids, tuple(sorted(claim.claim_id for claim in self.confirmed)))
        self.assertEqual(result.excluded_claim_ids, ())
        self.assertFalse(result.delivery_blocked)
        self.assertEqual(result.error_categories, {})

    def test_needs_review_and_accepted_claims_are_excluded_without_mutation(self) -> None:
        needs_review = replace(self.confirmed[0], review_status="needs_review")
        accepted = replace(self.confirmed[1], review_status="accepted")
        result = evaluate_doctor_view((needs_review, accepted))

        self.assertEqual(result.included_claim_ids, ())
        self.assertEqual(set(result.excluded_claim_ids), {needs_review.claim_id, accepted.claim_id})
        self.assertEqual(result.error_categories[DoctorViewErrorCategory.NOT_CONFIRMED.value], 2)
        self.assertTrue(result.delivery_blocked)
        self.assertEqual(needs_review.review_status.value, "needs_review")
        self.assertEqual(accepted.review_status.value, "accepted")

    def test_missing_source_reference_is_excluded(self) -> None:
        claim = self.confirmed[0]
        result = evaluate_doctor_view(
            ({
                "claim_id": claim.claim_id,
                "review_status": "confirmed",
                "source_type": claim.source_type,
                "source_span": claim.source_span,
            },)
        )

        self.assertEqual(result.included_claim_ids, ())
        self.assertIn(DoctorViewErrorCategory.SOURCE_REF_MISSING.value, result.error_categories)
        self.assertTrue(result.delivery_blocked)

    def test_missing_source_span_is_excluded(self) -> None:
        claim = replace(self.confirmed[0], source_span=None)
        result = evaluate_doctor_view((claim,))

        self.assertEqual(result.included_claim_ids, ())
        self.assertIn(DoctorViewErrorCategory.SOURCE_SPAN_MISSING.value, result.error_categories)
        self.assertTrue(result.delivery_blocked)

    def test_unresolved_conflict_excludes_affected_claims(self) -> None:
        case = synthetic_golden_set().cases[1]
        confirmed = tuple(replace(claim, review_status="confirmed") for claim in case.expected_claims)
        conflict = case.expected_conflicts[0]
        result = evaluate_doctor_view(confirmed, conflicts=(conflict,))

        self.assertEqual(result.included_claim_ids, ())
        self.assertEqual(set(result.excluded_claim_ids), set(conflict.claim_ids))
        self.assertEqual(result.error_categories[DoctorViewErrorCategory.CONFLICT_UNRESOLVED.value], 2)
        self.assertTrue(result.delivery_blocked)

    def test_gate_result_round_trips_json(self) -> None:
        result = evaluate_doctor_view(self.confirmed)
        restored = type(result).from_json(result.to_json())

        self.assertEqual(restored.to_dict(), result.to_dict())
        self.assertEqual(restored.schema_version, "1.0.0")

    def test_invalid_source_span_mapping_is_rejected(self) -> None:
        claim = self.confirmed[0]
        with self.assertRaises(ValueError):
            evaluate_doctor_view(({
                "claim_id": claim.claim_id,
                "review_status": "confirmed",
                "source_ref": claim.source_ref,
                "source_type": claim.source_type,
                "source_span": {"start": 2, "end": 1, "page": 1},
            },))


if __name__ == "__main__":
    unittest.main()
