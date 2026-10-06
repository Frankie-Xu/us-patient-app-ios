"""Provider-neutral AI pipeline orchestration.

This module keeps the production seam independent from any OCR or model SDK.
Providers implement the existing EvaluationPipeline stages; the adapter adds
deterministic normalization, source-span checks, conflict-aware doctor
summaries/questions, and redacted telemetry. Synthetic fixtures are the only
data used by the built-in implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable

from .pipeline import (
    CitationCoverageResult,
    ConflictDetectionResult,
    EvaluationPipeline,
    FactExtractionResult,
    OCRLayoutResult,
    PipelineError,
)
from .schema import Claim, Conflict, GoldenCase, OCRBlock, ReviewStatus, Severity, SourceSpan


@dataclass(frozen=True)
class ModelTelemetry:
    """Provider/model accounting for one pipeline invocation.

    input_units and output_units are provider-neutral token/character
    counters supplied by the caller. Raw document content and prompts are
    never retained in this record.
    """

    provider: str
    model_version: str
    input_units: int = 0
    output_units: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0

    def __post_init__(self) -> None:
        for field_name in ("provider", "model_version"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, value.strip())
        for field_name in ("input_units", "output_units"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        for field_name in ("cost_usd", "latency_ms"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)) or value < 0:
                raise ValueError(f"{field_name} must be a finite non-negative number")
            object.__setattr__(self, field_name, float(value))

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model_version": self.model_version,
            "input_units": self.input_units,
            "output_units": self.output_units,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
        }


@dataclass(frozen=True)
class TelemetrySummary:
    """Aggregate provider accounting without retaining document content."""

    provider: str
    model_versions: tuple[str, ...]
    sample_count: int
    total_input_units: int
    total_output_units: int
    total_cost_usd: float
    average_cost_usd: float
    total_latency_ms: float
    average_latency_ms: float

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("provider must be a non-empty string")
        versions = tuple(sorted(set(self.model_versions)))
        if not versions or any(not isinstance(value, str) or not value.strip() for value in versions):
            raise ValueError("model_versions must contain non-empty strings")
        if type(self.sample_count) is not int or self.sample_count < 1:
            raise ValueError("sample_count must be a positive integer")
        for field_name in ("total_input_units", "total_output_units"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        for field_name in (
            "total_cost_usd",
            "average_cost_usd",
            "total_latency_ms",
            "average_latency_ms",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)) or value < 0:
                raise ValueError(f"{field_name} must be a finite non-negative number")
            object.__setattr__(self, field_name, float(value))
        object.__setattr__(self, "model_versions", versions)

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model_versions": list(self.model_versions),
            "sample_count": self.sample_count,
            "total_input_units": self.total_input_units,
            "total_output_units": self.total_output_units,
            "total_cost_usd": self.total_cost_usd,
            "average_cost_usd": self.average_cost_usd,
            "total_latency_ms": self.total_latency_ms,
            "average_latency_ms": self.average_latency_ms,
        }


def summarize_telemetry(results: Iterable[ProviderPipelineResult]) -> TelemetrySummary:
    """Aggregate run-level model, cost and latency evidence for a report."""

    values = tuple(results)
    if not values:
        raise ValueError("at least one provider result is required")
    provider = values[0].telemetry.provider
    if any(result.telemetry.provider != provider for result in values):
        raise ValueError("telemetry summary cannot mix providers")
    total_cost = sum(result.telemetry.cost_usd for result in values)
    total_latency = sum(result.telemetry.latency_ms for result in values)
    return TelemetrySummary(
        provider=provider,
        model_versions=tuple(result.telemetry.model_version for result in values),
        sample_count=len(values),
        total_input_units=sum(result.telemetry.input_units for result in values),
        total_output_units=sum(result.telemetry.output_units for result in values),
        total_cost_usd=total_cost,
        average_cost_usd=total_cost / len(values),
        total_latency_ms=total_latency,
        average_latency_ms=total_latency / len(values),
    )


@dataclass(frozen=True)
class SourceSpanCheck:
    claim_id: str
    source_ref: str
    source_type: str
    source_span: SourceSpan
    block_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "source_ref": self.source_ref,
            "source_type": self.source_type,
            "source_span": {
                "start": self.source_span.start,
                "end": self.source_span.end,
                "page": self.source_span.page,
            },
            "block_id": self.block_id,
        }


@dataclass(frozen=True)
class DoctorQuestion:
    """A bilingual clarification prompt grounded in one extracted claim."""

    question_id: str
    claim_id: str
    text_en: str
    text_zh: str

    def __post_init__(self) -> None:
        for field_name in ("question_id", "claim_id", "text_en", "text_zh"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, value.strip())

    def to_dict(self) -> dict[str, str]:
        return {
            "question_id": self.question_id,
            "claim_id": self.claim_id,
            "text_en": self.text_en,
            "text_zh": self.text_zh,
        }


@dataclass(frozen=True)
class DoctorSummary:
    """A bounded, source-grounded bilingual summary with no clinical advice."""

    text_en: str
    text_zh: str
    claim_ids: tuple[str, ...]
    questions: tuple[DoctorQuestion, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("text_en", "text_zh"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, value.strip())
        ids = tuple(self.claim_ids)
        if any(not isinstance(value, str) or not value.strip() for value in ids):
            raise ValueError("claim_ids must contain non-empty strings")
        if len(set(ids)) != len(ids):
            raise ValueError("claim_ids must be unique")
        object.__setattr__(self, "claim_ids", ids)
        questions = tuple(self.questions)
        if not all(isinstance(item, DoctorQuestion) for item in questions):
            raise TypeError("questions must contain DoctorQuestion values")
        object.__setattr__(self, "questions", questions)

    def to_dict(self) -> dict[str, object]:
        return {
            "text_en": self.text_en,
            "text_zh": self.text_zh,
            "claim_ids": list(self.claim_ids),
            "questions": [question.to_dict() for question in self.questions],
        }


@dataclass(frozen=True)
class ProviderPipelineResult:
    case_id: str
    ocr: OCRLayoutResult
    normalized_ocr: OCRLayoutResult
    extraction: FactExtractionResult
    conflicts: ConflictDetectionResult
    citations: CitationCoverageResult
    span_checks: tuple[SourceSpanCheck, ...]
    doctor_summary: DoctorSummary
    telemetry: ModelTelemetry
    errors: tuple[PipelineError, ...] = ()

    @property
    def delivery_blocked(self) -> bool:
        return bool(self.citations.uncovered_claim_ids) or bool(self.errors) or bool(self.conflicts.conflicts)

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "ocr_block_count": len(self.ocr.blocks),
            "normalized_ocr_block_count": len(self.normalized_ocr.blocks),
            "claim_count": len(self.extraction.claims),
            "conflict_count": len(self.conflicts.conflicts),
            "citation_coverage": self.citations.coverage,
            "span_checks": [check.to_dict() for check in self.span_checks],
            "doctor_summary": self.doctor_summary.to_dict(),
            "telemetry": self.telemetry.to_dict(),
            "errors": [error.to_dict() for error in self.errors],
            "delivery_blocked": self.delivery_blocked,
        }


def normalize_ocr_layout(ocr: OCRLayoutResult) -> OCRLayoutResult:
    """Normalize whitespace while preserving block identity and provenance.

    text is left byte-for-byte intact because provider extractors may use an
    opaque format. The human-readable evidence field is normalized and source
    refs/types are never rewritten.
    """

    blocks: list[OCRBlock] = []
    errors = list(ocr.errors)
    for block in ocr.blocks:
        evidence = " ".join((block.evidence_text or block.text).split())
        if not evidence:
            errors.append(
                PipelineError(
                    code="normalization.empty_evidence",
                    message="OCR block has no evidence text",
                    severity=Severity.HIGH,
                )
            )
            continue
        blocks.append(
            OCRBlock(
                block_id=block.block_id,
                source_ref=block.source_ref,
                source_type=block.source_type,
                text=block.text,
                page=block.page,
                evidence_text=evidence,
            )
        )
    if not blocks:
        errors.append(
            PipelineError(
                code="normalization.no_blocks",
                message="normalization produced no usable OCR blocks",
                severity=Severity.HIGH,
            )
        )
    return OCRLayoutResult(case_id=ocr.case_id, blocks=tuple(blocks), errors=tuple(errors))


def align_source_spans(ocr: OCRLayoutResult, claims: Iterable[Claim]) -> tuple[tuple[SourceSpanCheck, ...], tuple[PipelineError, ...]]:
    """Resolve claim source spans to OCR blocks without changing claim values."""

    by_source: dict[tuple[str, str], list[OCRBlock]] = {}
    for block in ocr.blocks:
        by_source.setdefault((block.source_ref, block.source_type), []).append(block)
    checks: list[SourceSpanCheck] = []
    errors: list[PipelineError] = []
    for claim in claims:
        if claim.source_span is None:
            errors.append(
                PipelineError(
                    code="span.missing",
                    message="claim is missing a source span",
                    severity=Severity.HIGH,
                    claim_id=claim.claim_id,
                )
            )
            continue
        candidates = by_source.get((claim.source_ref, claim.source_type), ())
        if not candidates:
            errors.append(
                PipelineError(
                    code="span.source_unresolved",
                    message="claim source does not resolve to an OCR block",
                    severity=Severity.HIGH,
                    claim_id=claim.claim_id,
                )
            )
            continue
        block = next((candidate for candidate in candidates if candidate.page == claim.source_span.page), candidates[0])
        evidence_length = len(block.evidence_text or block.text)
        if claim.source_span.end > evidence_length:
            errors.append(
                PipelineError(
                    code="span.out_of_bounds",
                    message="claim source span exceeds OCR evidence length",
                    severity=Severity.HIGH,
                    claim_id=claim.claim_id,
                )
            )
            continue
        checks.append(
            SourceSpanCheck(
                claim_id=claim.claim_id,
                source_ref=claim.source_ref,
                source_type=claim.source_type,
                source_span=claim.source_span,
                block_id=block.block_id,
            )
        )
    return tuple(checks), tuple(errors)


def _doctor_summary(case_id: str, claims: tuple[Claim, ...], conflicts: tuple[Conflict, ...]) -> DoctorSummary:
    ordered_claims = tuple(sorted(claims, key=lambda claim: claim.claim_id))
    claim_ids = tuple(claim.claim_id for claim in ordered_claims)
    if ordered_claims:
        text_en = "Facts to review: " + "; ".join(claim.text_en for claim in ordered_claims)
        text_zh = "待核对事实：" + "；".join(claim.text_zh for claim in ordered_claims)
    else:
        text_en = "No facts were extracted from this document."
        text_zh = "未从该文档提取到事实。"
    conflicted = {claim_id for conflict in conflicts for claim_id in conflict.claim_ids}
    questions = []
    for claim in ordered_claims:
        if claim.review_status == ReviewStatus.CONFIRMED and claim.claim_id not in conflicted:
            continue
        questions.append(
            DoctorQuestion(
                question_id=f"{case_id}:question:{claim.claim_id}",
                claim_id=claim.claim_id,
                text_en=f"Please confirm this record: {claim.text_en}",
                text_zh=f"请确认这条记录：{claim.text_zh}",
            )
        )
    return DoctorSummary(text_en=text_en, text_zh=text_zh, claim_ids=claim_ids, questions=tuple(questions))


class ProviderNeutralPipeline:
    """Run all provider stages through one auditable, provider-neutral seam."""

    def __init__(self, provider: EvaluationPipeline) -> None:
        self.provider = provider

    def run(self, case: GoldenCase, *, telemetry: ModelTelemetry | None = None) -> ProviderPipelineResult:
        raw_ocr = self.provider.ocr_layout(case)
        normalized_ocr = normalize_ocr_layout(raw_ocr)
        extraction = self.provider.extract_facts(normalized_ocr)
        conflicts = self.provider.detect_conflicts(extraction)
        citations = self.provider.citation_coverage(normalized_ocr, extraction)
        span_checks, span_errors = align_source_spans(normalized_ocr, extraction.claims)
        total_input_units = sum(len(block.text) for block in normalized_ocr.blocks)
        total_output_units = sum(len(claim.text_en) + len(claim.text_zh) for claim in extraction.claims)
        captured_telemetry = telemetry or ModelTelemetry(
            provider=self.provider.provider,
            model_version=self.provider.version,
            input_units=total_input_units,
            output_units=total_output_units,
        )
        if captured_telemetry.provider != self.provider.provider:
            raise ValueError("telemetry provider does not match pipeline provider")
        errors = tuple(span_errors) + tuple(normalized_ocr.errors) + tuple(extraction.errors) + tuple(conflicts.errors)
        return ProviderPipelineResult(
            case_id=case.case_id,
            ocr=raw_ocr,
            normalized_ocr=normalized_ocr,
            extraction=extraction,
            conflicts=conflicts,
            citations=citations,
            span_checks=span_checks,
            doctor_summary=_doctor_summary(case.case_id, extraction.claims, conflicts.conflicts),
            telemetry=captured_telemetry,
            errors=errors,
        )
