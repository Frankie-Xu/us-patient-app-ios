"""Replaceable AI staging adapter for deterministic, de-identified fixtures.

The adapter composes the existing provider-free pipeline and doctor-view gate;
it does not introduce a second extraction or evaluation implementation.  Its
job is to make the staging boundary explicit: normalize OCR input, preserve
claim provenance, expose a review gate, and attach operational model metrics.

No claim is automatically confirmed.  A caller may pass explicit review event
IDs to :meth:`StagingAdapter.run`; low confidence, missing source spans and
conflicts remain blocked even after those events.
"""

from __future__ import annotations

import json
import math
import time
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

from .doctor_view import evaluate_doctor_view
from .pipeline import DeterministicStubPipeline, EvaluationPipeline, PipelineOutput
from .schema import Claim, Conflict, GoldenCase, ReviewStatus


ADAPTER_SCHEMA = "patient-app-ai/staging-adapter"
ADAPTER_SCHEMA_VERSION = "1.0.0"
REPORT_SCHEMA = "patient-app-ai/staging-regression-report"
REPORT_SCHEMA_VERSION = "1.0.0"
DEFAULT_LOW_CONFIDENCE_THRESHOLD = 0.8


def normalize_ocr_text(value: str) -> str:
    """Return deterministic OCR text while preserving synthetic FACT records.

    OCR engines commonly emit non-breaking spaces, compatibility characters,
    trailing whitespace and duplicate blank lines.  We normalize those at the
    staging boundary but retain the tab separating ``FACT`` from its JSON
    payload so the existing deterministic pipeline remains the sole parser.
    """

    if not isinstance(value, str) or not value.strip():
        raise ValueError("document_text must be a non-empty string")
    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    blank_pending = False
    for raw_line in normalized.split("\n"):
        line = raw_line.replace("\u00a0", " ").strip()
        if not line:
            blank_pending = bool(lines)
            continue
        if blank_pending:
            lines.append("")
            blank_pending = False
        if line.startswith("FACT\t"):
            # Keep the FACT delimiter and trim only whitespace outside it.
            lines.append("FACT\t" + line.split("\t", 1)[1].strip())
        else:
            # Horizontal whitespace is presentation noise for non-FACT OCR.
            lines.append(" ".join(line.split()))
    result = "\n".join(lines).strip()
    if not result:
        raise ValueError("document_text must contain non-empty OCR content")
    return result


@dataclass(frozen=True)
class StagingInput:
    """A de-identified document envelope accepted by the adapter."""

    case_id: str
    source_ref: str
    source_type: str
    document_text: str
    language: str = "bilingual"
    data_classification: str = "deidentified"

    def __post_init__(self) -> None:
        for field_name in ("case_id", "source_ref", "source_type", "document_text"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, value.strip() if field_name != "document_text" else value)
        language = self.language.strip().lower() if isinstance(self.language, str) else ""
        if language not in {"en", "zh", "bilingual"}:
            raise ValueError("language must be en, zh, or bilingual")
        object.__setattr__(self, "language", language)
        classification = self.data_classification.strip().lower() if isinstance(self.data_classification, str) else ""
        if classification not in {"synthetic", "deidentified"}:
            raise ValueError("data_classification must be synthetic or deidentified")
        object.__setattr__(self, "data_classification", classification)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StagingInput":
        if not isinstance(value, Mapping):
            raise ValueError("staging input must be an object")
        required = {"case_id", "source_ref", "source_type", "document_text"}
        missing = sorted(required - set(value))
        unknown = sorted(set(value) - required - {"language", "data_classification"})
        if missing:
            raise ValueError(f"staging input is missing fields: {', '.join(missing)}")
        if unknown:
            raise ValueError(f"staging input has unknown fields: {', '.join(unknown)}")
        return cls(
            case_id=value["case_id"],
            source_ref=value["source_ref"],
            source_type=value["source_type"],
            document_text=value["document_text"],
            language=value.get("language", "bilingual"),
            data_classification=value.get("data_classification", "deidentified"),
        )

    def normalized(self) -> "StagingInput":
        return replace(self, document_text=normalize_ocr_text(self.document_text))


def load_staging_inputs(path: str | Path) -> tuple[StagingInput, ...]:
    """Load a strict, de-identified staging fixture envelope."""

    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError("staging fixture must contain an object")
    required = {"dataset_id", "version", "data_classification", "cases"}
    missing = sorted(required - set(payload))
    unknown = sorted(set(payload) - required)
    if missing:
        raise ValueError(f"staging fixture is missing fields: {', '.join(missing)}")
    if unknown:
        raise ValueError(f"staging fixture has unknown fields: {', '.join(unknown)}")
    if payload["data_classification"] not in {"synthetic", "deidentified"}:
        raise ValueError("staging fixture data_classification must be synthetic or deidentified")
    cases = tuple(StagingInput.from_dict(item) for item in payload["cases"])
    if not cases:
        raise ValueError("staging fixture must contain at least one case")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("staging fixture case_id values must be unique")
    if any(case.data_classification != payload["data_classification"] for case in cases):
        raise ValueError("staging case classification must match the fixture")
    return cases


@dataclass(frozen=True)
class StagingReviewDecision:
    claim_id: str
    review_required: bool
    auto_confirmed: bool
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.claim_id, str) or not self.claim_id.strip():
            raise ValueError("review decision claim_id must be non-empty")
        if not isinstance(self.review_required, bool) or not isinstance(self.auto_confirmed, bool):
            raise ValueError("review decision flags must be booleans")
        if self.auto_confirmed:
            raise ValueError("staging adapter cannot auto-confirm a claim")
        normalized = tuple(dict.fromkeys(str(reason) for reason in self.reasons if str(reason).strip()))
        object.__setattr__(self, "reasons", normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "review_required": self.review_required,
            "auto_confirmed": self.auto_confirmed,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class StagingReviewGate:
    decisions: tuple[StagingReviewDecision, ...]
    delivery_blocked: bool
    error_categories: dict[str, int]

    def __post_init__(self) -> None:
        decisions = tuple(self.decisions)
        if len({decision.claim_id for decision in decisions}) != len(decisions):
            raise ValueError("review decisions must have unique claim IDs")
        if any(decision.auto_confirmed for decision in decisions):
            raise ValueError("staging review gate cannot contain auto-confirmed claims")
        if not isinstance(self.delivery_blocked, bool):
            raise ValueError("delivery_blocked must be a boolean")
        counts = {}
        for code, count in self.error_categories.items():
            if not isinstance(code, str) or type(count) is not int or count < 1:
                raise ValueError("error_categories must map strings to positive integers")
            counts[code] = count
        object.__setattr__(self, "decisions", tuple(sorted(decisions, key=lambda item: item.claim_id)))
        object.__setattr__(self, "error_categories", dict(sorted(counts.items())))

    @property
    def review_required_claim_ids(self) -> tuple[str, ...]:
        return tuple(decision.claim_id for decision in self.decisions if decision.review_required)

    @property
    def auto_confirmed_claim_ids(self) -> tuple[str, ...]:
        # Kept as a first-class field in the report to make accidental
        # confirmation leaks visible; the adapter always returns an empty tuple.
        return ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "decisions": [decision.to_dict() for decision in self.decisions],
            "review_required_claim_ids": list(self.review_required_claim_ids),
            "auto_confirmed_claim_ids": [],
            "delivery_blocked": self.delivery_blocked,
            "error_categories": dict(self.error_categories),
        }


@dataclass(frozen=True)
class StagingSummary:
    status: str
    provider: str
    version: str
    text_en: str = ""
    text_zh: str = ""
    source_claim_ids: tuple[str, ...] = ()
    blocked_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"ready", "blocked"}:
            raise ValueError("summary status must be ready or blocked")
        for field_name in ("provider", "version"):
            if not isinstance(getattr(self, field_name), str) or not getattr(self, field_name).strip():
                raise ValueError(f"summary {field_name} must be non-empty")
        if self.status == "ready" and (not self.text_en.strip() or not self.text_zh.strip()):
            raise ValueError("ready summary must contain bilingual text")
        if self.status == "blocked" and (self.text_en or self.text_zh):
            raise ValueError("blocked summary cannot contain summary text")
        object.__setattr__(self, "source_claim_ids", tuple(self.source_claim_ids))
        object.__setattr__(self, "blocked_reasons", tuple(dict.fromkeys(self.blocked_reasons)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "version": self.version,
            "text_en": self.text_en,
            "text_zh": self.text_zh,
            "source_claim_ids": list(self.source_claim_ids),
            "blocked_reasons": list(self.blocked_reasons),
        }


class SummaryProvider(Protocol):
    provider: str
    version: str

    def generate(
        self,
        claims: Iterable[Claim],
        conflicts: Iterable[Conflict],
        gate: StagingReviewGate,
    ) -> StagingSummary: ...


class DeterministicSummaryProvider:
    """Replaceable bilingual summary double with no clinical generation."""

    provider = "deterministic-summary"
    version = "1"

    def generate(
        self,
        claims: Iterable[Claim],
        conflicts: Iterable[Conflict],
        gate: StagingReviewGate,
    ) -> StagingSummary:
        selected = tuple(claims)
        if gate.delivery_blocked or not selected:
            reasons = tuple(sorted(gate.error_categories)) or ("summary.no_eligible_claims",)
            return StagingSummary(
                status="blocked",
                provider=self.provider,
                version=self.version,
                blocked_reasons=reasons,
            )
        return StagingSummary(
            status="ready",
            provider=self.provider,
            version=self.version,
            text_en=" ".join(claim.text_en for claim in selected),
            text_zh=" ".join(claim.text_zh for claim in selected),
            source_claim_ids=tuple(claim.claim_id for claim in selected),
        )


@dataclass(frozen=True)
class StagingRunMetadata:
    model_provider: str
    model_version: str
    summary_provider: str
    summary_version: str
    latency_ms: float
    cost_usd: float

    def __post_init__(self) -> None:
        for field_name in ("model_provider", "model_version", "summary_provider", "summary_version"):
            if not isinstance(getattr(self, field_name), str) or not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must be non-empty")
        for field_name in ("latency_ms", "cost_usd"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0:
                raise ValueError(f"{field_name} must be finite and non-negative")
            object.__setattr__(self, field_name, float(value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_provider": self.model_provider,
            "model_version": self.model_version,
            "summary_provider": self.summary_provider,
            "summary_version": self.summary_version,
            "latency_ms": self.latency_ms,
            "cost_usd": self.cost_usd,
        }


@dataclass(frozen=True)
class StagingOutput:
    case_id: str
    normalized_text: str
    pipeline: PipelineOutput
    gate: StagingReviewGate
    summary: StagingSummary
    metadata: StagingRunMetadata

    @property
    def delivery_blocked(self) -> bool:
        return self.gate.delivery_blocked or self.pipeline.delivery_blocked or self.summary.status == "blocked"

    def to_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "adapter_schema": ADAPTER_SCHEMA,
            "schema_version": ADAPTER_SCHEMA_VERSION,
            "case_id": self.case_id,
            "gate": self.gate.to_dict(),
            "summary": self.summary.to_dict(),
            "metadata": self.metadata.to_dict(),
            "delivery_blocked": self.delivery_blocked,
        }
        if include_content:
            result["normalized_text"] = self.normalized_text
            result["ocr_blocks"] = [
                {
                    "block_id": block.block_id,
                    "source_ref": block.source_ref,
                    "source_type": block.source_type,
                    "page": block.page,
                    "text": block.text,
                    "evidence_text": block.evidence_text,
                }
                for block in self.pipeline.ocr.blocks
            ]
            result["claims"] = [claim.to_dict() for claim in self.pipeline.extraction.claims]
            result["conflicts"] = [conflict.to_dict() for conflict in self.pipeline.conflicts.conflicts]
        return result


@dataclass(frozen=True)
class StagingRegressionReport:
    dataset_id: str
    dataset_version: str
    sample_count: int
    model_provider: str
    model_version: str
    metrics: dict[str, float]
    delivery_blocked: bool
    report_schema: str = REPORT_SCHEMA
    schema_version: str = REPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.report_schema != REPORT_SCHEMA or self.schema_version != REPORT_SCHEMA_VERSION:
            raise ValueError("staging regression report schema version drift")
        if not self.dataset_id.strip() or not self.dataset_version.strip():
            raise ValueError("dataset identity must be non-empty")
        if type(self.sample_count) is not int or self.sample_count < 1:
            raise ValueError("sample_count must be positive")
        if not self.model_provider.strip() or not self.model_version.strip():
            raise ValueError("model identity must be non-empty")
        for name, value in self.metrics.items():
            if not isinstance(name, str) or not name.strip() or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0:
                raise ValueError("metrics must be finite non-negative values")
        if not isinstance(self.delivery_blocked, bool):
            raise ValueError("delivery_blocked must be a boolean")
        object.__setattr__(self, "metrics", dict(sorted((name, float(value)) for name, value in self.metrics.items())))

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_schema": self.report_schema,
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "sample_count": self.sample_count,
            "model_provider": self.model_provider,
            "model_version": self.model_version,
            "metrics": dict(self.metrics),
            "delivery_blocked": self.delivery_blocked,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


class StagingAdapter:
    """Compose the existing pipeline and review gate for staging workflows."""

    def __init__(
        self,
        pipeline: EvaluationPipeline | None = None,
        summary_provider: SummaryProvider | None = None,
        *,
        low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
        clock: Callable[[], float] = time.perf_counter,
        cost_usd: float = 0.0,
    ) -> None:
        if isinstance(low_confidence_threshold, bool) or not isinstance(low_confidence_threshold, (int, float)) or not math.isfinite(float(low_confidence_threshold)) or not 0 <= float(low_confidence_threshold) <= 1:
            raise ValueError("low_confidence_threshold must be finite and between 0 and 1")
        if isinstance(cost_usd, bool) or not isinstance(cost_usd, (int, float)) or not math.isfinite(float(cost_usd)) or float(cost_usd) < 0:
            raise ValueError("cost_usd must be finite and non-negative")
        self.pipeline = pipeline or DeterministicStubPipeline()
        self.summary_provider = summary_provider or DeterministicSummaryProvider()
        self.low_confidence_threshold = float(low_confidence_threshold)
        self.clock = clock
        self.cost_usd = float(cost_usd)

    def _review_gate(self, claims: tuple[Claim, ...], conflicts: tuple[Conflict, ...]) -> StagingReviewGate:
        doctor_gate = evaluate_doctor_view(claims, conflicts=conflicts)
        conflict_ids = {claim_id for conflict in conflicts for claim_id in conflict.claim_ids}
        decisions: list[StagingReviewDecision] = []
        counts = dict(doctor_gate.error_categories)
        for claim in claims:
            reasons = list(
                decision.error_categories[i].value
                for decision in doctor_gate.decisions
                if decision.claim_id == claim.claim_id
                for i in range(len(decision.error_categories))
            )
            if claim.confidence < self.low_confidence_threshold:
                reasons.append("staging.low_confidence")
            if claim.claim_id in conflict_ids:
                reasons.append("staging.conflict_detected")
            reasons = list(dict.fromkeys(reasons))
            for reason in reasons:
                counts[reason] = counts.get(reason, 0) + 1
            decisions.append(
                StagingReviewDecision(
                    claim_id=claim.claim_id,
                    review_required=bool(reasons),
                    auto_confirmed=False,
                    reasons=tuple(reasons),
                )
            )
        return StagingReviewGate(
            decisions=tuple(decisions),
            delivery_blocked=bool(doctor_gate.delivery_blocked or any(decision.review_required for decision in decisions)),
            error_categories=counts,
        )

    def run(
        self,
        request: StagingInput,
        *,
        confirmed_claim_ids: Iterable[str] = (),
    ) -> StagingOutput:
        normalized = request.normalized()
        started = float(self.clock())
        case = GoldenCase(
            case_id=normalized.case_id,
            document_source_ref=normalized.source_ref,
            document_source_type=normalized.source_type,
            document_text=normalized.document_text,
            expected_claims=(),
            data_classification=normalized.data_classification,
        )
        pipeline_output = self.pipeline.run(case)
        explicit_ids = frozenset(confirmed_claim_ids)
        known_ids = {claim.claim_id for claim in pipeline_output.extraction.claims}
        unknown_ids = explicit_ids - known_ids
        if unknown_ids:
            raise ValueError("confirmed_claim_ids contains an unknown claim")
        claims = tuple(
            replace(claim, review_status=ReviewStatus.CONFIRMED) if claim.claim_id in explicit_ids else claim
            for claim in pipeline_output.extraction.claims
        )
        if claims != pipeline_output.extraction.claims:
            pipeline_output = replace(pipeline_output, extraction=replace(pipeline_output.extraction, claims=claims))
        conflicts = pipeline_output.conflicts.conflicts
        gate = self._review_gate(claims, conflicts)
        eligible = tuple(claim for claim in claims if not next(decision for decision in gate.decisions if decision.claim_id == claim.claim_id).review_required)
        summary = self.summary_provider.generate(eligible, conflicts, gate)
        if gate.delivery_blocked and summary.status == "ready":
            raise ValueError("summary provider attempted to bypass a blocked review gate")
        elapsed = max(0.0, (float(self.clock()) - started) * 1000.0)
        metadata = StagingRunMetadata(
            model_provider=self.pipeline.provider,
            model_version=self.pipeline.version,
            summary_provider=self.summary_provider.provider,
            summary_version=self.summary_provider.version,
            latency_ms=elapsed,
            cost_usd=self.cost_usd,
        )
        return StagingOutput(
            case_id=normalized.case_id,
            normalized_text=normalized.document_text,
            pipeline=pipeline_output,
            gate=gate,
            summary=summary,
            metadata=metadata,
        )

    def regression_report(
        self,
        inputs: Iterable[StagingInput],
        *,
        dataset_id: str = "patient-app-ai-staging",
        dataset_version: str = "1.0.0",
    ) -> StagingRegressionReport:
        outputs = tuple(self.run(item) for item in inputs)
        if not outputs:
            raise ValueError("staging regression requires at least one input")
        claim_count = sum(len(output.pipeline.extraction.claims) for output in outputs)
        required_count = sum(len(output.gate.review_required_claim_ids) for output in outputs)
        low_confidence_count = sum(output.gate.error_categories.get("staging.low_confidence", 0) for output in outputs)
        missing_span_count = sum(output.gate.error_categories.get("doctor_view.source_span_missing", 0) for output in outputs)
        conflict_count = sum(len(output.pipeline.conflicts.conflicts) for output in outputs)
        metrics = {
            "review_required_rate": required_count / claim_count if claim_count else 0.0,
            "low_confidence_claims": float(low_confidence_count),
            "missing_source_span_claims": float(missing_span_count),
            "conflicts": float(conflict_count),
            "summary_ready_cases": float(sum(output.summary.status == "ready" for output in outputs)),
            "latency_ms_total": sum(output.metadata.latency_ms for output in outputs),
            "latency_ms_average": sum(output.metadata.latency_ms for output in outputs) / len(outputs),
            "cost_usd_total": sum(output.metadata.cost_usd for output in outputs),
        }
        return StagingRegressionReport(
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            sample_count=len(outputs),
            model_provider=self.pipeline.provider,
            model_version=self.pipeline.version,
            metrics=metrics,
            delivery_blocked=any(output.delivery_blocked for output in outputs),
        )
