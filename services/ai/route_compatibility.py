"""HTTP-route compatibility checks for the frozen API v0.2.0 projection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from .api_projection import API_VERSION, ApiProjection, FactCreate, FactReview
from .output_evaluator import ErrorCategory


class RouteCompatibilityError(ValueError):
    """Raised when an HTTP payload cannot be consumed by the API v0.2.0 route."""


FACT_CREATE_FIELDS = frozenset(FactCreate(
    claim_id="_schema",
    text_en="_schema",
    text_zh="_schema",
    normalized_key="",
    normalized_value="",
    source_ref="synthetic:_schema",
    source_type="synthetic_schema",
    source_span=None,
    confidence=0.0,
    review_required=True,
    review_status="needs_review",
).to_dict())
FACT_REVIEW_FIELDS = frozenset(FactReview(
    claim_id="_schema",
    review_required=True,
    review_status="needs_review",
    error_categories=(),
).to_dict())
PROJECTION_FIELDS = frozenset({"api_version", "fact_creates", "fact_reviews"})


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RouteCompatibilityError(f"{path} must be an object")
    return value


def _fields(value: Mapping[str, Any], expected: frozenset[str], path: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise RouteCompatibilityError(f"{path} missing fields: {', '.join(missing)}")
    if unknown:
        raise RouteCompatibilityError(f"{path} has unknown fields: {', '.join(unknown)}")


def _review_invariants(fact: FactCreate | FactReview, path: str, confidence: float | None = None) -> None:
    categories = set(fact.error_categories)
    effective_confidence = fact.confidence if confidence is None and isinstance(fact, FactCreate) else confidence
    if effective_confidence is not None and effective_confidence < 0.8 and ErrorCategory.LOW_CONFIDENCE not in categories:
        raise RouteCompatibilityError(f"{path} low confidence must include low_confidence")
    missing_claim_without_source = ErrorCategory.MISSING_CLAIM in categories and getattr(fact, "source_ref", None) is None
    if fact.source_span is None and ErrorCategory.SOURCE_SPAN_MISSING not in categories and not missing_claim_without_source:
        raise RouteCompatibilityError(f"{path} missing source_span must include source_span_missing")
    if ErrorCategory.CONFLICT_DETECTED in categories and not fact.review_required:
        raise RouteCompatibilityError(f"{path} conflict_detected requires review_required")
    if ErrorCategory.CONFLICT_DETECTED in categories and fact.review_status.value not in {"needs_review", "rejected"}:
        raise RouteCompatibilityError(f"{path} conflict_detected cannot be confirmed")
    if not fact.review_required:
        raise RouteCompatibilityError(f"{path} must have review_required=true")


def validate_fact_create_payload(value: Mapping[str, Any], *, path: str = "fact_creates[]") -> FactCreate:
    payload = _mapping(value, path)
    _fields(payload, FACT_CREATE_FIELDS, path)
    try:
        fact = FactCreate.from_dict(payload)
    except (TypeError, ValueError, KeyError) as exc:
        raise RouteCompatibilityError(f"{path} is incompatible: {exc}") from exc
    _review_invariants(fact, path)
    return fact


def validate_fact_review_payload(value: Mapping[str, Any], *, path: str = "fact_reviews[]") -> FactReview:
    payload = _mapping(value, path)
    _fields(payload, FACT_REVIEW_FIELDS, path)
    try:
        review = FactReview.from_dict(payload)
    except (TypeError, ValueError, KeyError) as exc:
        raise RouteCompatibilityError(f"{path} is incompatible: {exc}") from exc
    _review_invariants(review, path, confidence=review.confidence)
    return review


@dataclass(frozen=True)
class RouteCompatibilityReport:
    api_version: str
    fact_create_count: int
    fact_review_count: int
    claim_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_version": self.api_version,
            "fact_create_count": self.fact_create_count,
            "fact_review_count": self.fact_review_count,
            "claim_ids": list(self.claim_ids),
        }


def validate_route_payload(value: Mapping[str, Any]) -> RouteCompatibilityReport:
    """Validate an HTTP JSON body and return route-level compatibility facts."""

    payload = _mapping(value, "projection")
    _fields(payload, PROJECTION_FIELDS, "projection")
    if payload["api_version"] != API_VERSION:
        raise RouteCompatibilityError(f"projection requires api_version {API_VERSION}")
    if not isinstance(payload["fact_creates"], list) or not isinstance(payload["fact_reviews"], list):
        raise RouteCompatibilityError("projection fact_creates and fact_reviews must be arrays")
    creates = tuple(validate_fact_create_payload(item, path=f"fact_creates[{index}]") for index, item in enumerate(payload["fact_creates"]))
    reviews = tuple(validate_fact_review_payload(item, path=f"fact_reviews[{index}]") for index, item in enumerate(payload["fact_reviews"]))
    create_ids = {fact.claim_id for fact in creates}
    review_ids = {review.claim_id for review in reviews}
    if not create_ids <= review_ids:
        missing_reviews = sorted(create_ids - review_ids)
        raise RouteCompatibilityError(f"projection is missing reviews for: {', '.join(missing_reviews)}")
    return RouteCompatibilityReport(
        api_version=API_VERSION,
        fact_create_count=len(creates),
        fact_review_count=len(reviews),
        claim_ids=tuple(sorted(review_ids)),
    )


def validate_route_json(value: str) -> RouteCompatibilityReport:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RouteCompatibilityError(f"projection is not valid JSON: {exc}") from exc
    return validate_route_payload(payload)


def projection_to_route_payload(projection: ApiProjection) -> dict[str, Any]:
    """Serialize a typed projection exactly as an HTTP route would consume it."""

    payload = projection.to_dict()
    validate_route_payload(payload)
    return payload
