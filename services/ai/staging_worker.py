"""Deterministic staging worker adapter for normalized OCR documents.

The worker composes the existing provider-neutral pipeline without changing its
evaluation, API projection, or golden-set contracts. It accepts synthetic or
de-identified normalized OCR text, emits the existing extraction and doctor
summary artifacts, and returns content-free confidence/review telemetry.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from math import isfinite
from typing import Iterable

from .pipeline import DeterministicStubPipeline, EvaluationPipeline
from .provider_pipeline import (
    ModelTelemetry,
    ProviderNeutralPipeline,
    ProviderPipelineResult,
)
from .schema import GoldenCase, ReviewStatus


@dataclass(frozen=True)
class StagingDocument:
    """Normalized OCR text entering the deterministic staging worker.

    The worker intentionally accepts text that has already passed an OCR
    adapter. Its built-in provider remains deterministic and only understands
    the checked-in synthetic FACT records.
    """

    case_id: str
    source_ref: str
    source_type: str
    normalized_ocr_text: str
    data_classification: str = "synthetic"

    def __post_init__(self) -> None:
        for field_name in ("case_id", "source_ref", "source_type", "normalized_ocr_text"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, value.strip())
        classification = self.data_classification.strip().lower() if isinstance(self.data_classification, str) else ""
        if classification not in {"synthetic", "deidentified"}:
            raise ValueError("data_classification must be synthetic or deidentified")
        object.__setattr__(self, "data_classification", classification)

    def to_case(self) -> GoldenCase:
        """Build a label-free envelope for the provider stages.

        expected_claims and expected_conflicts stay empty so the staging path
        cannot accidentally read evaluation labels.
        """

        return GoldenCase(
            case_id=self.case_id,
            document_source_ref=self.source_ref,
            document_source_type=self.source_type,
            document_text=self.normalized_ocr_text,
            expected_claims=(),
            expected_conflicts=(),
            data_classification=self.data_classification,
        )

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        digest.update(self.case_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(self.source_ref.encode("utf-8"))
        digest.update(b"\0")
        digest.update(self.source_type.encode("utf-8"))
        digest.update(b"\0")
        digest.update(self.normalized_ocr_text.encode("utf-8"))
        digest.update(b"\0")
        digest.update(self.data_classification.encode("utf-8"))
        return digest.hexdigest()


@dataclass(frozen=True)
class StagingWorkerRequest:
    """One idempotent staging invocation."""

    document: StagingDocument
    idempotency_key: str = ""
    telemetry: ModelTelemetry | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.document, StagingDocument):
            raise TypeError("document must be a StagingDocument")
        if not isinstance(self.idempotency_key, str):
            raise ValueError("idempotency_key must be a string")
        if self.idempotency_key and not self.idempotency_key.strip():
            raise ValueError("idempotency_key must not be blank")
        if self.telemetry is not None and not isinstance(self.telemetry, ModelTelemetry):
            raise TypeError("telemetry must be ModelTelemetry or None")
        object.__setattr__(self, "idempotency_key", self.idempotency_key.strip())

    @property
    def cache_key(self) -> str:
        """Return an explicit key or a deterministic content fingerprint."""

        return self.idempotency_key or self.document.fingerprint


@dataclass(frozen=True)
class StagingQualityMetrics:
    """Content-free quality and confirmation-gate counters.

    Rates are derived from counters so aggregate reports cannot be averaged
    incorrectly across cases with different claim counts.
    """

    case_count: int
    claim_count: int
    low_confidence_claim_count: int
    missing_source_claim_count: int
    conflict_case_count: int
    conflict_claim_count: int
    manual_review_claim_count: int
    confirmation_block_case_count: int

    def __post_init__(self) -> None:
        fields = (
            "case_count",
            "claim_count",
            "low_confidence_claim_count",
            "missing_source_claim_count",
            "conflict_case_count",
            "conflict_claim_count",
            "manual_review_claim_count",
            "confirmation_block_case_count",
        )
        for field_name in fields:
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.case_count == 0 and any(getattr(self, field_name) for field_name in fields[1:]):
            raise ValueError("zero cases cannot contain claim or gate counters")
        if self.low_confidence_claim_count > self.claim_count:
            raise ValueError("low confidence claims cannot exceed claim count")
        if self.missing_source_claim_count > self.claim_count:
            raise ValueError("missing source claims cannot exceed claim count")
        if self.manual_review_claim_count > self.claim_count:
            raise ValueError("manual review claims cannot exceed claim count")
        if self.conflict_case_count > self.case_count:
            raise ValueError("conflict cases cannot exceed case count")
        if self.confirmation_block_case_count > self.case_count:
            raise ValueError("confirmation block cases cannot exceed case count")

    @property
    def low_confidence_rate(self) -> float:
        return self.low_confidence_claim_count / self.claim_count if self.claim_count else 0.0

    @property
    def missing_source_rate(self) -> float:
        return self.missing_source_claim_count / self.claim_count if self.claim_count else 0.0

    @property
    def conflict_rate(self) -> float:
        return self.conflict_case_count / self.case_count if self.case_count else 0.0

    @property
    def manual_review_rate(self) -> float:
        return self.manual_review_claim_count / self.claim_count if self.claim_count else 0.0

    @property
    def confirmation_block_rate(self) -> float:
        return self.confirmation_block_case_count / self.case_count if self.case_count else 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "case_count": self.case_count,
            "claim_count": self.claim_count,
            "low_confidence_claim_count": self.low_confidence_claim_count,
            "missing_source_claim_count": self.missing_source_claim_count,
            "conflict_case_count": self.conflict_case_count,
            "conflict_claim_count": self.conflict_claim_count,
            "manual_review_claim_count": self.manual_review_claim_count,
            "confirmation_block_case_count": self.confirmation_block_case_count,
            "low_confidence_rate": self.low_confidence_rate,
            "missing_source_rate": self.missing_source_rate,
            "conflict_rate": self.conflict_rate,
            "manual_review_rate": self.manual_review_rate,
            "confirmation_block_rate": self.confirmation_block_rate,
        }

    @classmethod
    def from_results(
        cls,
        results: Iterable[ProviderPipelineResult],
        *,
        low_confidence_threshold: float = 0.8,
    ) -> "StagingQualityMetrics":
        """Aggregate metrics from one or more provider pipeline results."""

        _validate_threshold(low_confidence_threshold)
        values = tuple(results)
        if not values:
            raise ValueError("at least one provider pipeline result is required")
        counters = [0] * 8
        for result in values:
            current = _metrics_for_result(result, low_confidence_threshold)
            counters = [left + right for left, right in zip(counters, (
                current.case_count,
                current.claim_count,
                current.low_confidence_claim_count,
                current.missing_source_claim_count,
                current.conflict_case_count,
                current.conflict_claim_count,
                current.manual_review_claim_count,
                current.confirmation_block_case_count,
            ))]
        return cls(*counters)


@dataclass(frozen=True)
class StagingWorkerResult:
    """Existing extraction/summary artifacts plus staging telemetry."""

    idempotency_key: str
    pipeline: ProviderPipelineResult
    metrics: StagingQualityMetrics

    def __post_init__(self) -> None:
        if not isinstance(self.idempotency_key, str) or not self.idempotency_key.strip():
            raise ValueError("idempotency_key must be a non-empty string")
        if not isinstance(self.pipeline, ProviderPipelineResult):
            raise TypeError("pipeline must be a ProviderPipelineResult")
        if not isinstance(self.metrics, StagingQualityMetrics):
            raise TypeError("metrics must be StagingQualityMetrics")

    @property
    def extraction(self):
        return self.pipeline.extraction

    @property
    def doctor_summary(self):
        return self.pipeline.doctor_summary

    @property
    def delivery_blocked(self) -> bool:
        return self.pipeline.delivery_blocked or self.metrics.confirmation_block_case_count > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "idempotency_key": self.idempotency_key,
            "pipeline": self.pipeline.to_dict(),
            "metrics": self.metrics.to_dict(),
            "delivery_blocked": self.delivery_blocked,
        }


def _validate_threshold(value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)) or not 0 <= float(value) <= 1:
        raise ValueError("low_confidence_threshold must be a finite number between 0 and 1")


def _metrics_for_result(result: ProviderPipelineResult, low_confidence_threshold: float) -> StagingQualityMetrics:
    claims = tuple(result.extraction.claims)
    span_ids = {check.claim_id for check in result.span_checks}
    uncovered = set(result.citations.uncovered_claim_ids)
    low_confidence = {
        claim.claim_id for claim in claims if claim.confidence < low_confidence_threshold
    }
    missing_source = {
        claim.claim_id
        for claim in claims
        if claim.source_span is None or claim.claim_id not in span_ids or claim.claim_id in uncovered
    }
    conflict_claims = {
        claim_id for conflict in result.conflicts.conflicts for claim_id in conflict.claim_ids
    }
    manual_review = {
        claim.claim_id for claim in claims if claim.review_status != ReviewStatus.CONFIRMED
    }
    confirmation_blocked = bool(
        result.delivery_blocked
        or low_confidence
        or missing_source
        or conflict_claims
    )
    return StagingQualityMetrics(
        case_count=1,
        claim_count=len(claims),
        low_confidence_claim_count=len(low_confidence),
        missing_source_claim_count=len(missing_source),
        conflict_case_count=1 if result.conflicts.conflicts else 0,
        conflict_claim_count=len(conflict_claims),
        manual_review_claim_count=len(manual_review),
        confirmation_block_case_count=1 if confirmation_blocked else 0,
    )


class StagingAIWorker:
    """Run the provider-neutral pipeline with deterministic idempotency."""

    def __init__(
        self,
        provider: EvaluationPipeline | None = None,
        *,
        low_confidence_threshold: float = 0.8,
    ) -> None:
        _validate_threshold(low_confidence_threshold)
        self.provider = provider or DeterministicStubPipeline()
        self.pipeline = ProviderNeutralPipeline(self.provider)
        self.low_confidence_threshold = float(low_confidence_threshold)
        self._completed: dict[str, tuple[str, StagingWorkerResult]] = {}

    def process(self, request: StagingWorkerRequest) -> StagingWorkerResult:
        if not isinstance(request, StagingWorkerRequest):
            raise TypeError("request must be a StagingWorkerRequest")
        key = request.cache_key
        fingerprint = request.document.fingerprint
        cached = self._completed.get(key)
        if cached is not None:
            cached_fingerprint, result = cached
            if cached_fingerprint != fingerprint:
                raise ValueError("idempotency key was reused for a different document")
            return result

        result = self.pipeline.run(request.document.to_case(), telemetry=request.telemetry)
        metrics = _metrics_for_result(result, self.low_confidence_threshold)
        worker_result = StagingWorkerResult(
            idempotency_key=key,
            pipeline=result,
            metrics=metrics,
        )
        self._completed[key] = (fingerprint, worker_result)
        return worker_result

    def run(self, request: StagingWorkerRequest) -> StagingWorkerResult:
        """Alias for callers that model a worker as a run operation."""

        return self.process(request)


def aggregate_quality_metrics(
    results: Iterable[StagingWorkerResult],
) -> StagingQualityMetrics:
    """Aggregate content-free metrics from completed worker results."""

    values = tuple(results)
    if not values:
        raise ValueError("at least one staging worker result is required")
    counters = [sum(getattr(result.metrics, field_name) for result in values) for field_name in (
        "case_count",
        "claim_count",
        "low_confidence_claim_count",
        "missing_source_claim_count",
        "conflict_case_count",
        "conflict_claim_count",
        "manual_review_claim_count",
        "confirmation_block_case_count",
    )]
    return StagingQualityMetrics(*counters)
