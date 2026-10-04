"""Deterministic eligibility gate for the doctor-facing view."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from .schema import Claim, Conflict, ReviewStatus, SourceSpan


GATE_SCHEMA = "patient-app-ai/doctor-view-gate"
GATE_SCHEMA_VERSION = "1.0.0"


class DoctorViewErrorCategory(str, Enum):
    NOT_CONFIRMED = "doctor_view.not_confirmed"
    SOURCE_REF_MISSING = "doctor_view.source_ref_missing"
    SOURCE_TYPE_MISSING = "doctor_view.source_type_missing"
    SOURCE_SPAN_MISSING = "doctor_view.source_span_missing"
    CONFLICT_UNRESOLVED = "doctor_view.conflict_unresolved"


@dataclass(frozen=True)
class _GateFact:
    claim_id: str
    review_status: ReviewStatus
    source_ref: str | None
    source_type: str | None
    source_span: SourceSpan | None


def _span(value: Any) -> SourceSpan | None:
    if value is None:
        return None
    if isinstance(value, SourceSpan):
        return value
    if isinstance(value, Mapping):
        try:
            return SourceSpan(start=value.get("start"), end=value.get("end"), page=value.get("page", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid source_span: {exc}") from exc
    raise ValueError("source_span must be a SourceSpan, object or null")


def _fact(value: Claim | Mapping[str, Any]) -> _GateFact:
    if isinstance(value, Claim):
        return _GateFact(
            claim_id=value.claim_id,
            review_status=value.review_status,
            source_ref=value.source_ref,
            source_type=value.source_type,
            source_span=value.source_span,
        )
    if not isinstance(value, Mapping):
        raise ValueError("doctor-view facts must be Claim or mapping values")
    claim_id = value.get("claim_id")
    if not isinstance(claim_id, str) or not claim_id.strip():
        raise ValueError("doctor-view fact claim_id must be a non-empty string")
    try:
        status = value.get("review_status")
        status = status if isinstance(status, ReviewStatus) else ReviewStatus(status)
    except (TypeError, ValueError) as exc:
        raise ValueError("doctor-view fact has an invalid review_status") from exc
    return _GateFact(
        claim_id=claim_id,
        review_status=status,
        source_ref=value.get("source_ref"),
        source_type=value.get("source_type"),
        source_span=_span(value.get("source_span")),
    )


@dataclass(frozen=True)
class DoctorViewDecision:
    claim_id: str
    included: bool
    review_status: ReviewStatus
    error_categories: tuple[DoctorViewErrorCategory, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "included": self.included,
            "review_status": self.review_status.value,
            "error_categories": [category.value for category in self.error_categories],
        }


@dataclass(frozen=True)
class DoctorViewGateResult:
    gate_schema: str
    schema_version: str
    included_claim_ids: tuple[str, ...]
    excluded_claim_ids: tuple[str, ...]
    error_categories: dict[str, int]
    delivery_blocked: bool
    decisions: tuple[DoctorViewDecision, ...]

    def __post_init__(self) -> None:
        if self.gate_schema != GATE_SCHEMA:
            raise ValueError(f"doctor-view gate requires schema {GATE_SCHEMA}")
        if self.schema_version != GATE_SCHEMA_VERSION:
            raise ValueError(f"doctor-view gate requires version {GATE_SCHEMA_VERSION}")
        if not isinstance(self.delivery_blocked, bool):
            raise ValueError("delivery_blocked must be a boolean")
        if set(self.included_claim_ids) & set(self.excluded_claim_ids):
            raise ValueError("a claim cannot be both included and excluded")
        normalized = {}
        for code, count in self.error_categories.items():
            if not isinstance(code, str) or type(count) is not int or count < 1:
                raise ValueError("error_categories must map strings to positive integers")
            normalized[code] = count
        object.__setattr__(self, "included_claim_ids", tuple(sorted(self.included_claim_ids)))
        object.__setattr__(self, "excluded_claim_ids", tuple(sorted(self.excluded_claim_ids)))
        object.__setattr__(self, "error_categories", dict(sorted(normalized.items())))

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_schema": self.gate_schema,
            "schema_version": self.schema_version,
            "included_claim_ids": list(self.included_claim_ids),
            "excluded_claim_ids": list(self.excluded_claim_ids),
            "error_categories": dict(self.error_categories),
            "delivery_blocked": self.delivery_blocked,
            "decisions": [decision.to_dict() for decision in self.decisions],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DoctorViewGateResult":
        required = {
            "gate_schema",
            "schema_version",
            "included_claim_ids",
            "excluded_claim_ids",
            "error_categories",
            "delivery_blocked",
            "decisions",
        }
        missing = sorted(required - set(value))
        unknown = sorted(set(value) - required)
        if missing:
            raise ValueError(f"doctor-view result is missing fields: {', '.join(missing)}")
        if unknown:
            raise ValueError(f"doctor-view result has unknown fields: {', '.join(unknown)}")
        decisions = []
        for item in value["decisions"]:
            decisions.append(
                DoctorViewDecision(
                    claim_id=item["claim_id"],
                    included=item["included"],
                    review_status=ReviewStatus(item["review_status"]),
                    error_categories=tuple(DoctorViewErrorCategory(category) for category in item.get("error_categories", ())),
                )
            )
        return cls(
            gate_schema=value["gate_schema"],
            schema_version=value["schema_version"],
            included_claim_ids=tuple(value["included_claim_ids"]),
            excluded_claim_ids=tuple(value["excluded_claim_ids"]),
            error_categories=dict(value["error_categories"]),
            delivery_blocked=value["delivery_blocked"],
            decisions=tuple(decisions),
        )

    @classmethod
    def from_json(cls, value: str) -> "DoctorViewGateResult":
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"doctor-view result is not valid JSON: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("doctor-view result JSON must contain an object")
        return cls.from_dict(payload)


def evaluate_doctor_view(
    claims: Iterable[Claim | Mapping[str, Any]],
    *,
    conflicts: Iterable[Conflict] = (),
) -> DoctorViewGateResult:
    """Return an auditable inclusion decision without changing claim state."""

    facts = tuple(_fact(value) for value in claims)
    if len({fact.claim_id for fact in facts}) != len(facts):
        raise ValueError("doctor-view claims must have unique claim_id values")
    conflict_ids = {claim_id for conflict in conflicts for claim_id in conflict.claim_ids}
    counts: dict[str, int] = {}
    decisions: list[DoctorViewDecision] = []
    included: list[str] = []
    excluded: list[str] = []
    for fact in facts:
        categories: list[DoctorViewErrorCategory] = []
        if fact.review_status != ReviewStatus.CONFIRMED:
            categories.append(DoctorViewErrorCategory.NOT_CONFIRMED)
        if not isinstance(fact.source_ref, str) or not fact.source_ref.strip():
            categories.append(DoctorViewErrorCategory.SOURCE_REF_MISSING)
        if not isinstance(fact.source_type, str) or not fact.source_type.strip():
            categories.append(DoctorViewErrorCategory.SOURCE_TYPE_MISSING)
        if fact.source_span is None:
            categories.append(DoctorViewErrorCategory.SOURCE_SPAN_MISSING)
        if fact.claim_id in conflict_ids:
            categories.append(DoctorViewErrorCategory.CONFLICT_UNRESOLVED)
        categories = list(dict.fromkeys(categories))
        for category in categories:
            counts[category.value] = counts.get(category.value, 0) + 1
        included_flag = not categories
        (included if included_flag else excluded).append(fact.claim_id)
        decisions.append(
            DoctorViewDecision(
                claim_id=fact.claim_id,
                included=included_flag,
                review_status=fact.review_status,
                error_categories=tuple(categories),
            )
        )
    return DoctorViewGateResult(
        gate_schema=GATE_SCHEMA,
        schema_version=GATE_SCHEMA_VERSION,
        included_claim_ids=tuple(included),
        excluded_claim_ids=tuple(excluded),
        error_categories=counts,
        delivery_blocked=bool(excluded),
        decisions=tuple(sorted(decisions, key=lambda decision: decision.claim_id)),
    )
