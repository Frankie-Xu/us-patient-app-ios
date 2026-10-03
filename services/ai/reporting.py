"""Regression metrics and delivery-blocker reporting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .pipeline import DeterministicStubPipeline, PipelineError, PipelineOutput
from .schema import Claim, GoldenCase, GoldenSet, Severity


METRIC_FIELDS = (
    "precision",
    "recall",
    "citation_coverage",
    "rewrite_rate",
    "rejection_rate",
    "per_case_cost",
)


@dataclass(frozen=True)
class CaseMetrics:
    case_id: str
    precision: float
    recall: float
    citation_coverage: float
    rewrite_rate: float
    rejection_rate: float
    per_case_cost: float
    errors: tuple[PipelineError, ...] = ()
    delivery_blocked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "precision": self.precision,
            "recall": self.recall,
            "citation_coverage": self.citation_coverage,
            "rewrite_rate": self.rewrite_rate,
            "rejection_rate": self.rejection_rate,
            "per_case_cost": self.per_case_cost,
            "errors": [error.to_dict() for error in self.errors],
            "delivery_blocked": self.delivery_blocked,
        }


@dataclass(frozen=True)
class RegressionReport:
    dataset_id: str
    dataset_version: str
    pipeline: str
    cases: tuple[CaseMetrics, ...]
    metrics: dict[str, float]
    delivery_blocked: bool
    blocking_errors: tuple[PipelineError, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "pipeline": self.pipeline,
            "metrics": dict(self.metrics),
            "cases": [case.to_dict() for case in self.cases],
            "delivery_blocked": self.delivery_blocked,
            "blocking_errors": [error.to_dict() for error in self.blocking_errors],
        }


def _claim_matches(expected: Claim, actual: Claim) -> bool:
    return (
        expected.claim_id == actual.claim_id
        and expected.text_en == actual.text_en
        and expected.text_zh == actual.text_zh
        and expected.source_ref == actual.source_ref
        and expected.source_type == actual.source_type
    )


def _error(code: str, message: str, severity: Severity, claim_id: str = "") -> PipelineError:
    return PipelineError(code=code, message=message, severity=severity, claim_id=claim_id)


def evaluate_case(case: GoldenCase, output: PipelineOutput, per_case_cost: float | None = None) -> CaseMetrics:
    """Compare a pipeline output to expected labels without calling a provider."""

    effective_cost = output.per_case_cost if per_case_cost is None else per_case_cost
    if isinstance(effective_cost, bool) or not isinstance(effective_cost, (int, float)) or effective_cost < 0:
        raise ValueError("per_case_cost must be non-negative")
    expected_by_id = {claim.claim_id: claim for claim in case.expected_claims}
    actual_by_id = {claim.claim_id: claim for claim in output.extraction.claims}
    errors: list[PipelineError] = list(output.all_errors)
    true_positives = 0

    for claim_id, expected in expected_by_id.items():
        actual = actual_by_id.get(claim_id)
        if actual is None:
            errors.append(_error("regression.missing_claim", "expected claim was not emitted", Severity.HIGH, claim_id))
        elif _claim_matches(expected, actual):
            true_positives += 1
        else:
            errors.append(
                _error(
                    "regression.provenance_mismatch",
                    "claim_id was emitted with a different citation",
                    Severity.HIGH,
                    claim_id,
                )
            )

    for claim_id in actual_by_id.keys() - expected_by_id.keys():
        errors.append(_error("regression.unexpected_claim", "pipeline emitted an unexpected claim", Severity.MEDIUM, claim_id))

    for claim_id in output.citations.uncovered_claim_ids:
        errors.append(_error("regression.citation_uncovered", "claim citation does not resolve to an OCR source", Severity.HIGH, claim_id))

    expected_count = len(expected_by_id)
    actual_count = len(actual_by_id)
    precision = true_positives / actual_count if actual_count else (1.0 if expected_count == 0 else 0.0)
    recall = true_positives / expected_count if expected_count else 1.0
    rewrite_count = sum(1 for claim in output.extraction.claims if claim.rewritten)
    rejection_count = sum(1 for claim in output.extraction.claims if claim.review_status.value == "rejected")
    rewrite_rate = rewrite_count / actual_count if actual_count else 0.0
    rejection_rate = rejection_count / actual_count if actual_count else 0.0

    for conflict in output.conflicts.conflicts:
        errors.append(
            _error(
                "regression.conflict",
                conflict.reason or "conflicting claims detected",
                conflict.severity,
            )
        )
    for expected_conflict in case.expected_conflicts:
        expected_ids = set(expected_conflict.claim_ids)
        if not any(expected_ids == set(conflict.claim_ids) for conflict in output.conflicts.conflicts):
            errors.append(
                _error(
                    "regression.missing_conflict",
                    "expected conflict was not detected",
                    expected_conflict.severity,
                )
            )

    expected_citation_ids = {
        claim.claim_id
        for claim_id, claim in expected_by_id.items()
        if (actual := actual_by_id.get(claim_id)) is not None
        and actual.source_ref == claim.source_ref
        and actual.source_type == claim.source_type
    }
    citation_coverage = len(expected_citation_ids) / expected_count if expected_count else 1.0
    delivery_blocked = any(error.blocks_delivery for error in errors)
    return CaseMetrics(
        case_id=case.case_id,
        precision=precision,
        recall=recall,
        citation_coverage=citation_coverage,
        rewrite_rate=rewrite_rate,
        rejection_rate=rejection_rate,
        per_case_cost=float(effective_cost),
        errors=tuple(errors),
        delivery_blocked=delivery_blocked,
    )


def _average(cases: Iterable[CaseMetrics], field_name: str) -> float:
    values = [float(getattr(case, field_name)) for case in cases]
    return sum(values) / len(values) if values else 0.0


def evaluate_golden_set(
    golden_set: GoldenSet,
    pipeline: DeterministicStubPipeline | None = None,
    per_case_cost: float | None = None,
) -> RegressionReport:
    """Run every case and return metrics plus any delivery blockers."""

    pipeline = pipeline or DeterministicStubPipeline()
    case_metrics = tuple(evaluate_case(case, pipeline.run(case), per_case_cost) for case in golden_set.cases)
    metrics = {field_name: _average(case_metrics, field_name) for field_name in METRIC_FIELDS}
    blocking_errors = tuple(
        error for case in case_metrics for error in case.errors if error.blocks_delivery
    )
    return RegressionReport(
        dataset_id=golden_set.dataset_id,
        dataset_version=golden_set.version,
        pipeline=f"{pipeline.provider}@{pipeline.version}",
        cases=case_metrics,
        metrics=metrics,
        delivery_blocked=bool(blocking_errors),
        blocking_errors=blocking_errors,
    )
