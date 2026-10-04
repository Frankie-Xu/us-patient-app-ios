"""Typed, serialisable contracts for AI evaluation.

The types in this module deliberately model source and review metadata next
to the claim text.  A consumer cannot construct a valid claim without a
claim id, citation, confidence and review state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping


class ReviewStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def blocks_delivery(self) -> bool:
        return self in {Severity.HIGH, Severity.CRITICAL}


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _as_enum(value: Any, enum_type: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ValueError(f"{field_name} must be one of: {allowed}") from exc


@dataclass(frozen=True)
class OCRBlock:
    """A source-located block emitted by OCR/layout."""

    source_ref: str
    source_type: str
    text: str
    page: int = 1
    block_id: str = ""
    evidence_text: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_ref", _required_text(self.source_ref, "source_ref"))
        object.__setattr__(self, "source_type", _required_text(self.source_type, "source_type"))
        object.__setattr__(self, "text", _required_text(self.text, "text"))
        if not isinstance(self.page, int) or self.page < 1:
            raise ValueError("page must be a positive integer")
        if self.block_id:
            object.__setattr__(self, "block_id", _required_text(self.block_id, "block_id"))


@dataclass(frozen=True)
class SourceSpan:
    """A character span inside a cited source block."""

    start: int
    end: int
    page: int = 1

    def __post_init__(self) -> None:
        if type(self.start) is not int or type(self.end) is not int:
            raise ValueError("source span offsets must be integers")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("source span must have 0 <= start < end")
        if type(self.page) is not int or self.page < 1:
            raise ValueError("source span page must be a positive integer")


@dataclass(frozen=True)
class Claim:
    """A bilingual fact with mandatory provenance and review metadata."""

    claim_id: str
    text_en: str
    text_zh: str
    source_ref: str
    source_type: str
    confidence: float
    review_status: ReviewStatus
    normalized_key: str = ""
    normalized_value: str = ""
    rewritten: bool = False
    source_span: SourceSpan | None = None

    def __post_init__(self) -> None:
        for field_name in ("claim_id", "text_en", "text_zh", "source_ref", "source_type"):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), field_name))
        if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
            raise ValueError("confidence must be a number between 0 and 1")
        if not 0 <= float(self.confidence) <= 1:
            raise ValueError("confidence must be a number between 0 and 1")
        object.__setattr__(self, "confidence", float(self.confidence))
        object.__setattr__(self, "review_status", _as_enum(self.review_status, ReviewStatus, "review_status"))
        if not isinstance(self.normalized_key, str) or not isinstance(self.normalized_value, str):
            raise ValueError("normalized_key and normalized_value must be strings")
        if self.normalized_key:
            object.__setattr__(self, "normalized_key", _required_text(self.normalized_key, "normalized_key"))
        if self.normalized_value:
            object.__setattr__(self, "normalized_value", _required_text(self.normalized_value, "normalized_value"))
        if not isinstance(self.rewritten, bool):
            raise ValueError("rewritten must be a boolean")
        if self.source_span is not None and not isinstance(self.source_span, SourceSpan):
            raise ValueError("source_span must be a SourceSpan or null")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["review_status"] = self.review_status.value
        return result


@dataclass(frozen=True)
class Conflict:
    """Two or more claims that disagree on a normalised fact."""

    conflict_id: str
    claim_ids: tuple[str, ...]
    severity: Severity = Severity.HIGH
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "conflict_id", _required_text(self.conflict_id, "conflict_id"))
        ids = tuple(_required_text(item, "claim_ids") for item in self.claim_ids)
        if len(ids) < 2 or len(set(ids)) != len(ids):
            raise ValueError("claim_ids must contain at least two distinct claim ids")
        object.__setattr__(self, "claim_ids", ids)
        object.__setattr__(self, "severity", _as_enum(self.severity, Severity, "severity"))
        if self.reason:
            object.__setattr__(self, "reason", _required_text(self.reason, "reason"))

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["severity"] = self.severity.value
        result["claim_ids"] = list(self.claim_ids)
        return result


@dataclass(frozen=True)
class GoldenCase:
    """One synthetic/de-identified document and its expected labels."""

    case_id: str
    document_source_ref: str
    document_source_type: str
    document_text: str
    expected_claims: tuple[Claim, ...]
    expected_conflicts: tuple[Conflict, ...] = ()
    data_classification: str = "synthetic"

    def __post_init__(self) -> None:
        for field_name in ("case_id", "document_source_ref", "document_source_type", "document_text"):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), field_name))
        classification = _required_text(self.data_classification, "data_classification").lower()
        if classification not in {"synthetic", "deidentified"}:
            raise ValueError("data_classification must be synthetic or deidentified")
        object.__setattr__(self, "data_classification", classification)
        claims = tuple(self.expected_claims)
        if not all(isinstance(claim, Claim) for claim in claims):
            raise TypeError("expected_claims must contain Claim values")
        if len({claim.claim_id for claim in claims}) != len(claims):
            raise ValueError("duplicate claim_id in case")
        object.__setattr__(self, "expected_claims", claims)
        conflicts = tuple(self.expected_conflicts)
        if not all(isinstance(conflict, Conflict) for conflict in conflicts):
            raise TypeError("expected_conflicts must contain Conflict values")
        claim_ids = {claim.claim_id for claim in claims}
        if any(not set(conflict.claim_ids) <= claim_ids for conflict in conflicts):
            raise ValueError("conflict references an unknown expected claim")
        if len({conflict.conflict_id for conflict in conflicts}) != len(conflicts):
            raise ValueError("duplicate conflict_id in case")
        object.__setattr__(self, "expected_conflicts", conflicts)


@dataclass(frozen=True)
class GoldenSet:
    """Versioned collection of cases used for regression evaluation."""

    dataset_id: str
    version: str
    cases: tuple[GoldenCase, ...]
    data_classification: str = "synthetic"

    def __post_init__(self) -> None:
        object.__setattr__(self, "dataset_id", _required_text(self.dataset_id, "dataset_id"))
        object.__setattr__(self, "version", _required_text(self.version, "version"))
        classification = _required_text(self.data_classification, "data_classification").lower()
        if classification not in {"synthetic", "deidentified"}:
            raise ValueError("data_classification must be synthetic or deidentified")
        object.__setattr__(self, "data_classification", classification)
        cases = tuple(self.cases)
        if not cases:
            raise ValueError("golden set must contain at least one case")
        if not all(isinstance(case, GoldenCase) for case in cases):
            raise TypeError("cases must contain GoldenCase values")
        if len({case.case_id for case in cases}) != len(cases):
            raise ValueError("duplicate case_id in golden set")
        if any(case.data_classification not in {"synthetic", "deidentified"} for case in cases):
            raise ValueError("golden set cannot contain real patient data")
        object.__setattr__(self, "cases", cases)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "version": self.version,
            "data_classification": self.data_classification,
            "cases": [
                {
                    "case_id": case.case_id,
                    "data_classification": case.data_classification,
                    "document": {
                        "source_ref": case.document_source_ref,
                        "source_type": case.document_source_type,
                        "text": case.document_text,
                    },
                    "expected_claims": [claim.to_dict() for claim in case.expected_claims],
                    "expected_conflicts": [conflict.to_dict() for conflict in case.expected_conflicts],
                }
                for case in self.cases
            ],
        }


def claim_from_dict(value: Mapping[str, Any], *, require_source_span: bool = False) -> Claim:
    """Build a claim while preserving strict required-field validation."""

    required = {"claim_id", "text_en", "text_zh", "source_ref", "source_type", "confidence", "review_status"}
    if require_source_span:
        required.add("source_span")
    missing = sorted(required - set(value))
    if missing:
        raise ValueError(f"claim is missing required fields: {', '.join(missing)}")
    payload = dict(value)
    if payload.get("source_span") is not None:
        span = payload["source_span"]
        if not isinstance(span, Mapping):
            raise ValueError("source_span must be an object")
        payload["source_span"] = SourceSpan(**dict(span))
    return Claim(**payload)
