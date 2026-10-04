"""Fixed, provider-free predictions used to exercise evaluator error classes."""

from __future__ import annotations

from dataclasses import replace
from enum import Enum

from .golden_set import synthetic_golden_set
from .schema import Claim, GoldenCase, ReviewStatus, SourceSpan


class MockPredictionVariant(str, Enum):
    PERFECT = "perfect"
    FIELD_VALUE_MISMATCH = "field_value_mismatch"
    SOURCE_SPAN_MISMATCH = "source_span_mismatch"
    LOW_CONFIDENCE = "low_confidence"
    REVIEW_REQUIRED_MISSING = "review_required_missing"
    MISSING_CLAIM = "missing_claim"
    UNEXPECTED_CLAIM = "unexpected_claim"


def fixed_mock_predictions(case: GoldenCase | None = None) -> dict[MockPredictionVariant, tuple[Claim, ...]]:
    """Return stable mock variants derived only from synthetic labels.

    The variants are intentionally small and predictable so evaluator tests do
    not depend on a model snapshot. They are not clinical predictions.
    """

    selected_case = case or synthetic_golden_set().cases[0]
    if selected_case.data_classification != "synthetic":
        raise ValueError("mock predictions require synthetic data")
    base = tuple(replace(claim, review_status=ReviewStatus.NEEDS_REVIEW) for claim in selected_case.expected_claims)
    if len(base) != 2:
        raise ValueError("fixed mock predictions require exactly two expected claims")
    first, second = base[0], base[1]
    variants: dict[MockPredictionVariant, tuple[Claim, ...]] = {
        MockPredictionVariant.PERFECT: base,
        MockPredictionVariant.FIELD_VALUE_MISMATCH: (
            replace(first, text_en="Synthetic replacement value."),
            second,
        ),
        MockPredictionVariant.SOURCE_SPAN_MISMATCH: (
            replace(first, source_span=SourceSpan(start=1, end=max(2, first.source_span.end if first.source_span else 2), page=1)),
            second,
        ),
        MockPredictionVariant.LOW_CONFIDENCE: (
            replace(first, confidence=0.4),
            second,
        ),
        MockPredictionVariant.REVIEW_REQUIRED_MISSING: (
            replace(first, review_status=ReviewStatus.ACCEPTED),
            second,
        ),
        MockPredictionVariant.MISSING_CLAIM: (first,),
        MockPredictionVariant.UNEXPECTED_CLAIM: (
            first,
            second,
            replace(second, claim_id="synthetic-unexpected-001", normalized_key="synthetic:unexpected"),
        ),
    }
    return variants
