"""Offline evaluator for extraction outputs and API review decisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Any, Iterable

from .schema import Claim, GoldenCase, OCRBlock, ReviewStatus, Severity


class ErrorCategory(str, Enum):
    """Stable categories consumed by regression reports and review tooling."""

    FIELD_VALUE_MISMATCH = "field_value_mismatch"
    SOURCE_SPAN_MISSING = "source_span_missing"
    SOURCE_SPAN_MISMATCH = "source_span_mismatch"
    CONFIDENCE_MISMATCH = "confidence_mismatch"
    REVIEW_REQUIRED_MISSING = "review_required_missing"
    REVIEW_REQUIRED_EXTRA = "review_required_extra"
    MISSING_CLAIM = "missing_claim"
    UNEXPECTED_CLAIM = "unexpected_claim"
    SOURCE_REFERENCE_MISMATCH = "source_reference_mismatch"
    SOURCE_SPAN_UNRESOLVED = "source_span_unresolved"
    LOW_CONFIDENCE = "low_confidence"
    CONFLICT_DETECTED = "conflict_detected"


VALUE_FIELDS = ("text_en", "text_zh", "normalized_key", "normalized_value")


@dataclass(frozen=True)
class ClassifiedError:
    category: ErrorCategory
    claim_id: str
    severity: Severity
    field: str = ""

    @property
    def blocks_delivery(self) -> bool:
        return self.severity.blocks_delivery

    def to_dict(self) -> dict[str, str]:
        result = {
            "category": self.category.value,
            "claim_id": self.claim_id,
            "severity": self.severity.value,
        }
        if self.field:
            result["field"] = self.field
        return result


@dataclass(frozen=True)
class ReviewDecision:
    """Review state that can be passed directly to an API review boundary."""

    claim_id: str
    review_required: bool
    review_status: ReviewStatus
    error_categories: tuple[ErrorCategory, ...] = ()

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "review_required": self.review_required,
            "review_status": self.review_status.value,
            "error_categories": [category.value for category in self.error_categories],
        }


@dataclass(frozen=True)
class ExtractionMetrics:
    field_value_accuracy: float
    source_span_accuracy: float
    confidence_mae: float
    review_required_precision: float
    review_required_recall: float
    error_count: int
    blocking_error_count: int

    def to_dict(self) -> dict[str, float | int]:
        return {
            "field_value_accuracy": self.field_value_accuracy,
            "source_span_accuracy": self.source_span_accuracy,
            "confidence_mae": self.confidence_mae,
            "review_required_precision": self.review_required_precision,
            "review_required_recall": self.review_required_recall,
            "error_count": self.error_count,
            "blocking_error_count": self.blocking_error_count,
        }


@dataclass(frozen=True)
class ExtractionEvaluation:
    case_id: str
    metrics: ExtractionMetrics
    errors: tuple[ClassifiedError, ...]
    review_decisions: tuple[ReviewDecision, ...]
    delivery_blocked: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "metrics": self.metrics.to_dict(),
            "errors": [error.to_dict() for error in self.errors],
            "review_decisions": [decision.to_api_dict() for decision in self.review_decisions],
            "delivery_blocked": self.delivery_blocked,
        }


def _requires_review(status: ReviewStatus) -> bool:
    return status in {ReviewStatus.UNREVIEWED, ReviewStatus.NEEDS_REVIEW, ReviewStatus.REJECTED}


def _normalise_claims(claims: Iterable[Claim]) -> dict[str, Claim]:
    result: dict[str, Claim] = {}
    for claim in claims:
        if claim.claim_id in result:
            raise ValueError(f"duplicate predicted claim_id: {claim.claim_id}")
        result[claim.claim_id] = claim
    return result


def evaluate_extraction_output(
    case: GoldenCase,
    predictions: Iterable[Claim],
    *,
    confidence_tolerance: float = 0.1,
    ocr_blocks: Iterable[OCRBlock] | None = None,
) -> ExtractionEvaluation:
    """Compare predictions to labels without accessing a model or network.

    The evaluator emits a review decision for every predicted claim. Any
    prediction with a blocking error is downgraded from ``accepted`` to
    ``needs_review`` so the returned state is safe for an API review queue.
    """

    if isinstance(confidence_tolerance, bool) or not isinstance(confidence_tolerance, (int, float)):
        raise ValueError("confidence_tolerance must be a finite non-negative number")
    if not isfinite(float(confidence_tolerance)) or confidence_tolerance < 0:
        raise ValueError("confidence_tolerance must be a finite non-negative number")

    expected = {claim.claim_id: claim for claim in case.expected_claims}
    actual = _normalise_claims(predictions)
    blocks = tuple(ocr_blocks) if ocr_blocks is not None else None
    errors: list[ClassifiedError] = []
    decisions_by_id: dict[str, ReviewDecision] = {}
    value_matches = 0
    value_total = len(expected) * len(VALUE_FIELDS)
    span_matches = 0
    span_total = sum(1 for claim in expected.values() if claim.source_span is not None)
    confidence_deltas: list[float] = []
    expected_review_ids = {claim_id for claim_id, claim in expected.items() if _requires_review(claim.review_status)}
    actual_review_ids = {claim_id for claim_id, claim in actual.items() if _requires_review(claim.review_status)}

    for claim_id, expected_claim in expected.items():
        predicted = actual.get(claim_id)
        claim_errors: list[ErrorCategory] = []
        if predicted is None:
            errors.append(ClassifiedError(ErrorCategory.MISSING_CLAIM, claim_id, Severity.HIGH))
            claim_errors.append(ErrorCategory.MISSING_CLAIM)
            decisions_by_id[claim_id] = ReviewDecision(
                claim_id=claim_id,
                review_required=True,
                review_status=ReviewStatus.REJECTED,
                error_categories=tuple(claim_errors),
            )
            continue

        for field_name in VALUE_FIELDS:
            if getattr(expected_claim, field_name) == getattr(predicted, field_name):
                value_matches += 1
            else:
                errors.append(ClassifiedError(ErrorCategory.FIELD_VALUE_MISMATCH, claim_id, Severity.HIGH, field_name))
                claim_errors.append(ErrorCategory.FIELD_VALUE_MISMATCH)

        reference_matches = (predicted.source_ref, predicted.source_type) == (expected_claim.source_ref, expected_claim.source_type)
        if not reference_matches:
            errors.append(ClassifiedError(ErrorCategory.SOURCE_REFERENCE_MISMATCH, claim_id, Severity.HIGH))
            claim_errors.append(ErrorCategory.SOURCE_REFERENCE_MISMATCH)
        span = predicted.source_span
        span_matches_gold = expected_claim.source_span is None or (span is not None and span == expected_claim.source_span)
        resolved = blocks is None or (span is not None and any(
            block.source_ref == predicted.source_ref and block.source_type == predicted.source_type
            and block.page == span.page and span.end <= len(block.evidence_text or block.text)
            for block in blocks
        ))
        if expected_claim.source_span is not None:
            if not span_matches_gold:
                category = ErrorCategory.SOURCE_SPAN_MISSING if span is None else ErrorCategory.SOURCE_SPAN_MISMATCH
                errors.append(ClassifiedError(category, claim_id, Severity.HIGH, "source_span"))
                claim_errors.append(category)
            if not resolved:
                errors.append(ClassifiedError(ErrorCategory.SOURCE_SPAN_UNRESOLVED, claim_id, Severity.HIGH))
                claim_errors.append(ErrorCategory.SOURCE_SPAN_UNRESOLVED)
            if reference_matches and span_matches_gold and resolved:
                span_matches += 1

        confidence_delta = abs(expected_claim.confidence - predicted.confidence)
        confidence_deltas.append(confidence_delta)
        if confidence_delta > confidence_tolerance:
            errors.append(ClassifiedError(ErrorCategory.CONFIDENCE_MISMATCH, claim_id, Severity.MEDIUM, "confidence"))
            claim_errors.append(ErrorCategory.CONFIDENCE_MISMATCH)

        expected_requires_review = claim_id in expected_review_ids
        actual_requires_review = claim_id in actual_review_ids
        if expected_requires_review and not actual_requires_review:
            errors.append(ClassifiedError(ErrorCategory.REVIEW_REQUIRED_MISSING, claim_id, Severity.HIGH, "review_status"))
            claim_errors.append(ErrorCategory.REVIEW_REQUIRED_MISSING)
        elif not expected_requires_review and actual_requires_review:
            errors.append(ClassifiedError(ErrorCategory.REVIEW_REQUIRED_EXTRA, claim_id, Severity.LOW, "review_status"))
            claim_errors.append(ErrorCategory.REVIEW_REQUIRED_EXTRA)

        # Evaluation cannot authorize confirmation, even for a perfect prediction.
        status = ReviewStatus.REJECTED if predicted.review_status == ReviewStatus.REJECTED else ReviewStatus.NEEDS_REVIEW
        decisions_by_id[claim_id] = ReviewDecision(
            claim_id=claim_id,
            review_required=status != ReviewStatus.ACCEPTED,
            review_status=status,
            error_categories=tuple(dict.fromkeys(claim_errors)),
        )

    for claim_id in sorted(set(actual) - set(expected)):
        errors.append(ClassifiedError(ErrorCategory.UNEXPECTED_CLAIM, claim_id, Severity.HIGH))
        predicted = actual[claim_id]
        status = ReviewStatus.NEEDS_REVIEW if predicted.review_status == ReviewStatus.ACCEPTED else predicted.review_status
        decisions_by_id[claim_id] = ReviewDecision(
            claim_id=claim_id,
            review_required=True,
            review_status=status,
            error_categories=(ErrorCategory.UNEXPECTED_CLAIM,),
        )

    field_value_accuracy = value_matches / value_total if value_total else 1.0
    source_span_accuracy = span_matches / span_total if span_total else 1.0
    confidence_mae = sum(confidence_deltas) / len(confidence_deltas) if confidence_deltas else 0.0
    review_precision = (
        len(expected_review_ids & actual_review_ids) / len(actual_review_ids)
        if actual_review_ids
        else (1.0 if not expected_review_ids else 0.0)
    )
    review_recall = (
        len(expected_review_ids & actual_review_ids) / len(expected_review_ids)
        if expected_review_ids
        else 1.0
    )
    metrics = ExtractionMetrics(
        field_value_accuracy=field_value_accuracy,
        source_span_accuracy=source_span_accuracy,
        confidence_mae=confidence_mae,
        review_required_precision=review_precision,
        review_required_recall=review_recall,
        error_count=len(errors),
        blocking_error_count=sum(1 for error in errors if error.blocks_delivery),
    )
    return ExtractionEvaluation(
        case_id=case.case_id,
        metrics=metrics,
        errors=tuple(errors),
        review_decisions=tuple(decisions_by_id[claim_id] for claim_id in sorted(decisions_by_id)),
        delivery_blocked=metrics.blocking_error_count > 0,
    )
