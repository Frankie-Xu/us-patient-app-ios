"""Projection from AI evaluation output to the API review boundary.

The API contract version is kept local to this adapter so the evaluator can be
tested without changing the frozen contracts package. AI output is never
projected as ``confirmed``; confirmation is a later, explicit human review
event owned by the API.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Any, Iterable, Mapping

from .output_evaluator import ErrorCategory, ExtractionEvaluation
from .schema import Claim, Conflict, ReviewStatus, SourceSpan


API_VERSION = "0.2.0"


class ApiReviewStatus(str, Enum):
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


def _status(value: Any) -> ApiReviewStatus:
    try:
        return value if isinstance(value, ApiReviewStatus) else ApiReviewStatus(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("AI projection review_status must be needs_review or rejected") from exc


def _span_to_dict(span: SourceSpan | None) -> dict[str, int] | None:
    if span is None:
        return None
    return {"start": span.start, "end": span.end, "page": span.page}


def _span_from_dict(value: Any) -> SourceSpan | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("source_span must be an object or null")
    return SourceSpan(start=value.get("start"), end=value.get("end"), page=value.get("page", 1))


def _categories(values: Iterable[ErrorCategory | str]) -> tuple[ErrorCategory, ...]:
    result: list[ErrorCategory] = []
    for value in values:
        category = value if isinstance(value, ErrorCategory) else ErrorCategory(value)
        if category not in result:
            result.append(category)
    return tuple(result)


@dataclass(frozen=True)
class FactCreate:
    """API v0.2.0 create payload for an AI-produced fact."""

    claim_id: str
    text_en: str
    text_zh: str
    normalized_key: str
    normalized_value: str
    source_ref: str
    source_type: str
    source_span: SourceSpan | None
    confidence: float
    review_required: bool
    review_status: ApiReviewStatus
    error_categories: tuple[ErrorCategory, ...] = ()
    api_version: str = API_VERSION

    def __post_init__(self) -> None:
        if self.api_version != API_VERSION:
            raise ValueError(f"FactCreate requires API version {API_VERSION}")
        for field_name in ("claim_id", "text_en", "text_zh", "source_ref", "source_type"):
            if not isinstance(getattr(self, field_name), str) or not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if not isinstance(self.normalized_key, str) or not isinstance(self.normalized_value, str):
            raise ValueError("normalized_key and normalized_value must be strings")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise ValueError("confidence must be a finite number between 0 and 1")
        if not isfinite(float(self.confidence)) or not 0 <= float(self.confidence) <= 1:
            raise ValueError("confidence must be a finite number between 0 and 1")
        if not isinstance(self.review_required, bool) or not self.review_required:
            raise ValueError("AI-created facts must have review_required=true")
        object.__setattr__(self, "confidence", float(self.confidence))
        object.__setattr__(self, "review_status", _status(self.review_status))
        object.__setattr__(self, "error_categories", _categories(self.error_categories))
        if self.review_status == ApiReviewStatus.NEEDS_REVIEW and not self.review_required:
            raise ValueError("needs_review facts must require review")

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_version": self.api_version,
            "claim_id": self.claim_id,
            "text_en": self.text_en,
            "text_zh": self.text_zh,
            "normalized_key": self.normalized_key,
            "normalized_value": self.normalized_value,
            "source_ref": self.source_ref,
            "source_type": self.source_type,
            "source_span": _span_to_dict(self.source_span),
            "confidence": self.confidence,
            "review_required": self.review_required,
            "review_status": self.review_status.value,
            "error_categories": [category.value for category in self.error_categories],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FactCreate":
        return cls(
            api_version=value.get("api_version", ""),
            claim_id=value.get("claim_id", ""),
            text_en=value.get("text_en", ""),
            text_zh=value.get("text_zh", ""),
            normalized_key=value.get("normalized_key", ""),
            normalized_value=value.get("normalized_value", ""),
            source_ref=value.get("source_ref", ""),
            source_type=value.get("source_type", ""),
            source_span=_span_from_dict(value.get("source_span")),
            confidence=value.get("confidence"),
            review_required=value.get("review_required"),
            review_status=value.get("review_status"),
            error_categories=tuple(value.get("error_categories", ())),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, value: str) -> "FactCreate":
        return cls.from_dict(json.loads(value))


@dataclass(frozen=True)
class FactReview:
    """API v0.2.0 review queue payload derived from an AI decision."""

    claim_id: str
    review_required: bool
    review_status: ApiReviewStatus
    error_categories: tuple[ErrorCategory, ...]
    confidence: float | None = None
    source_ref: str | None = None
    source_type: str | None = None
    source_span: SourceSpan | None = None
    api_version: str = API_VERSION

    def __post_init__(self) -> None:
        if self.api_version != API_VERSION:
            raise ValueError(f"FactReview requires API version {API_VERSION}")
        if not isinstance(self.claim_id, str) or not self.claim_id.strip():
            raise ValueError("claim_id must be a non-empty string")
        if not isinstance(self.review_required, bool) or not self.review_required:
            raise ValueError("AI review payloads must have review_required=true")
        object.__setattr__(self, "review_status", _status(self.review_status))
        object.__setattr__(self, "error_categories", _categories(self.error_categories))
        if self.confidence is not None:
            if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)) or not isfinite(float(self.confidence)) or not 0 <= float(self.confidence) <= 1:
                raise ValueError("confidence must be null or a finite number between 0 and 1")
            object.__setattr__(self, "confidence", float(self.confidence))
        if (self.source_ref is None) != (self.source_type is None):
            raise ValueError("source_ref and source_type must be both present or both null")

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_version": self.api_version,
            "claim_id": self.claim_id,
            "review_required": self.review_required,
            "review_status": self.review_status.value,
            "error_categories": [category.value for category in self.error_categories],
            "confidence": self.confidence,
            "source_ref": self.source_ref,
            "source_type": self.source_type,
            "source_span": _span_to_dict(self.source_span),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FactReview":
        return cls(
            api_version=value.get("api_version", ""),
            claim_id=value.get("claim_id", ""),
            review_required=value.get("review_required"),
            review_status=value.get("review_status"),
            error_categories=tuple(value.get("error_categories", ())),
            confidence=value.get("confidence"),
            source_ref=value.get("source_ref"),
            source_type=value.get("source_type"),
            source_span=_span_from_dict(value.get("source_span")),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, value: str) -> "FactReview":
        return cls.from_dict(json.loads(value))


@dataclass(frozen=True)
class ApiProjection:
    api_version: str
    fact_creates: tuple[FactCreate, ...]
    fact_reviews: tuple[FactReview, ...]

    def __post_init__(self) -> None:
        if self.api_version != API_VERSION:
            raise ValueError(f"ApiProjection requires API version {API_VERSION}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_version": self.api_version,
            "fact_creates": [fact.to_dict() for fact in self.fact_creates],
            "fact_reviews": [review.to_dict() for review in self.fact_reviews],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ApiProjection":
        return cls(
            api_version=value.get("api_version", ""),
            fact_creates=tuple(FactCreate.from_dict(item) for item in value.get("fact_creates", ())),
            fact_reviews=tuple(FactReview.from_dict(item) for item in value.get("fact_reviews", ())),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, value: str) -> "ApiProjection":
        return cls.from_dict(json.loads(value))


def project_evaluation(
    evaluation: ExtractionEvaluation,
    predictions: Iterable[Claim],
    *,
    conflicts: Iterable[Conflict] = (),
    low_confidence_threshold: float = 0.8,
) -> ApiProjection:
    """Map evaluated AI output into review-required API payloads."""

    if isinstance(low_confidence_threshold, bool) or not isinstance(low_confidence_threshold, (int, float)) or not isfinite(float(low_confidence_threshold)) or not 0 <= float(low_confidence_threshold) <= 1:
        raise ValueError("low_confidence_threshold must be a finite number between 0 and 1")
    claims = {claim.claim_id: claim for claim in predictions}
    decisions = {decision.claim_id: decision for decision in evaluation.review_decisions}
    conflict_ids = {
        claim_id
        for conflict in conflicts
        for claim_id in conflict.claim_ids
    }
    fact_creates: list[FactCreate] = []
    fact_reviews: list[FactReview] = []
    for claim_id, claim in claims.items():
        decision = decisions.get(claim_id)
        if decision is None:
            raise ValueError(f"evaluation has no review decision for {claim_id}")
        categories = list(decision.error_categories)
        if claim.confidence < low_confidence_threshold:
            categories.append(ErrorCategory.LOW_CONFIDENCE)
        if claim.source_span is None:
            categories.append(ErrorCategory.SOURCE_SPAN_MISSING)
        if claim_id in conflict_ids:
            categories.append(ErrorCategory.CONFLICT_DETECTED)
        categories = list(_categories(categories))
        status = ApiReviewStatus.REJECTED if decision.review_status == ReviewStatus.REJECTED else ApiReviewStatus.NEEDS_REVIEW
        fact_creates.append(
            FactCreate(
                claim_id=claim.claim_id,
                text_en=claim.text_en,
                text_zh=claim.text_zh,
                normalized_key=claim.normalized_key,
                normalized_value=claim.normalized_value,
                source_ref=claim.source_ref,
                source_type=claim.source_type,
                source_span=claim.source_span,
                confidence=claim.confidence,
                review_required=True,
                review_status=status,
                error_categories=tuple(categories),
            )
        )

    for decision in evaluation.review_decisions:
        claim = claims.get(decision.claim_id)
        categories = list(decision.error_categories)
        if claim is not None:
            if claim.confidence < low_confidence_threshold:
                categories.append(ErrorCategory.LOW_CONFIDENCE)
            if claim.source_span is None:
                categories.append(ErrorCategory.SOURCE_SPAN_MISSING)
            if claim.claim_id in conflict_ids:
                categories.append(ErrorCategory.CONFLICT_DETECTED)
        status = ApiReviewStatus.REJECTED if decision.review_status == ReviewStatus.REJECTED else ApiReviewStatus.NEEDS_REVIEW
        fact_reviews.append(
            FactReview(
                claim_id=decision.claim_id,
                review_required=True,
                review_status=status,
                error_categories=_categories(categories),
                confidence=claim.confidence if claim is not None else None,
                source_ref=claim.source_ref if claim is not None else None,
                source_type=claim.source_type if claim is not None else None,
                source_span=claim.source_span if claim is not None else None,
            )
        )
    return ApiProjection(api_version=API_VERSION, fact_creates=tuple(fact_creates), fact_reviews=tuple(fact_reviews))
