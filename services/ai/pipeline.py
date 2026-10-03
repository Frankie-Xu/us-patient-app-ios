"""Deterministic interfaces that future OCR/model providers must implement."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from math import isfinite
from typing import Protocol

from .schema import Claim, Conflict, GoldenCase, OCRBlock, ReviewStatus, Severity, claim_from_dict


@dataclass(frozen=True)
class PipelineError:
    code: str
    message: str
    severity: Severity = Severity.MEDIUM
    claim_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "severity", Severity(self.severity))

    @property
    def blocks_delivery(self) -> bool:
        return self.severity.blocks_delivery

    def to_dict(self) -> dict[str, str]:
        result = {"code": self.code, "message": self.message, "severity": self.severity.value}
        if self.claim_id:
            result["claim_id"] = self.claim_id
        return result


@dataclass(frozen=True)
class OCRLayoutResult:
    case_id: str
    blocks: tuple[OCRBlock, ...]
    errors: tuple[PipelineError, ...] = ()


@dataclass(frozen=True)
class FactExtractionResult:
    case_id: str
    claims: tuple[Claim, ...]
    errors: tuple[PipelineError, ...] = ()


@dataclass(frozen=True)
class ConflictDetectionResult:
    case_id: str
    conflicts: tuple[Conflict, ...]
    errors: tuple[PipelineError, ...] = ()


@dataclass(frozen=True)
class CitationCoverageResult:
    case_id: str
    covered_claim_ids: tuple[str, ...]
    uncovered_claim_ids: tuple[str, ...]

    @property
    def coverage(self) -> float:
        total = len(self.covered_claim_ids) + len(self.uncovered_claim_ids)
        return len(self.covered_claim_ids) / total if total else 1.0


@dataclass(frozen=True)
class PipelineOutput:
    case_id: str
    ocr: OCRLayoutResult
    extraction: FactExtractionResult
    conflicts: ConflictDetectionResult
    citations: CitationCoverageResult
    errors: tuple[PipelineError, ...] = ()
    per_case_cost: float = 0.0

    def __post_init__(self) -> None:
        if isinstance(self.per_case_cost, bool) or not isinstance(self.per_case_cost, (int, float)):
            raise ValueError("per_case_cost must be a finite non-negative USD amount")
        if not isfinite(self.per_case_cost) or self.per_case_cost < 0:
            raise ValueError("per_case_cost must be a finite non-negative USD amount")

    @property
    def all_errors(self) -> tuple[PipelineError, ...]:
        return self.ocr.errors + self.extraction.errors + self.conflicts.errors + self.errors

    @property
    def delivery_blocked(self) -> bool:
        return bool(self.citations.uncovered_claim_ids) or any(
            claim.review_status == ReviewStatus.ACCEPTED for claim in self.extraction.claims
        ) or any(error.blocks_delivery for error in self.all_errors) or any(
            conflict.severity.blocks_delivery for conflict in self.conflicts.conflicts
        )


class EvaluationPipeline(Protocol):
    """Replaceable offline evaluation adapter; stages must not read gold labels.

    Only run() receives the fixture envelope. Implementations use its document
    fields and must never read expected_claims or expected_conflicts.
    """

    provider: str
    version: str

    def ocr_layout(self, case: GoldenCase) -> OCRLayoutResult: ...
    def extract_facts(self, ocr: OCRLayoutResult) -> FactExtractionResult: ...
    def detect_conflicts(self, extraction: FactExtractionResult) -> ConflictDetectionResult: ...
    def citation_coverage(self, ocr: OCRLayoutResult, extraction: FactExtractionResult) -> CitationCoverageResult: ...
    def run(self, case: GoldenCase) -> PipelineOutput: ...


class DeterministicStubPipeline:
    """A provider-free, repeatable pipeline used to validate the boundary.

    Synthetic fixture documents encode facts as JSON lines beginning with
    ``FACT<TAB>``.  This is intentionally a transparent test format, not a
    proposed clinical-document parser.  No network or model-provider call is
    made by any method in this class.
    """

    provider = "deterministic-stub"
    version = "1"

    def ocr_layout(self, case: GoldenCase) -> OCRLayoutResult:
        blocks: list[OCRBlock] = []
        errors: list[PipelineError] = []
        for line_number, line in enumerate(case.document_text.splitlines(), start=1):
            text = line.strip()
            if not text:
                continue
            source_ref = f"{case.document_source_ref}:line-{line_number}"
            source_type = case.document_source_type
            if text.startswith("FACT\t"):
                try:
                    payload = json.loads(text.split("\t", 1)[1])
                    if not isinstance(payload, dict):
                        raise ValueError("expected an object")
                    source_ref = payload.get("source_ref", source_ref)
                    source_type = payload.get("source_type", source_type)
                    if not isinstance(source_ref, str) or not source_ref.strip():
                        raise ValueError("invalid reference")
                    if not isinstance(source_type, str) or not source_type.strip():
                        raise ValueError("invalid source type")
                except (ValueError, TypeError):
                    source_ref = f"{case.document_source_ref}:line-{line_number}"
                    source_type = case.document_source_type
                    errors.append(
                        PipelineError(
                            code="ocr.fact_payload_invalid",
                            message=f"line {line_number} has invalid synthetic FACT metadata",
                            severity=Severity.HIGH,
                        )
                    )
            blocks.append(
                OCRBlock(
                    block_id=f"{case.case_id}:block-{line_number}",
                    source_ref=source_ref,
                    source_type=source_type,
                    text=text,
                    page=1,
                )
            )
        if not blocks:
            errors.append(
                PipelineError(
                    code="ocr.no_blocks",
                    message="document produced no OCR/layout blocks",
                    severity=Severity.HIGH,
                )
            )
        return OCRLayoutResult(case_id=case.case_id, blocks=tuple(blocks), errors=tuple(errors))

    def extract_facts(self, ocr: OCRLayoutResult) -> FactExtractionResult:
        claims: list[Claim] = []
        errors: list[PipelineError] = []
        for block in ocr.blocks:
            if not block.text.startswith("FACT\t"):
                continue
            try:
                payload = json.loads(block.text.split("\t", 1)[1])
                if not isinstance(payload, dict):
                    raise ValueError("expected an object")
                claim = claim_from_dict(payload)
                # Source-encoded review state is not an authorized review event.
                claims.append(replace(claim, review_status=ReviewStatus.NEEDS_REVIEW))
            except (ValueError, TypeError):
                errors.append(
                    PipelineError(
                        code="extraction.claim_invalid",
                        message="a source block cannot become a valid bilingual claim",
                        severity=Severity.HIGH,
                    )
                )
        ids = [claim.claim_id for claim in claims]
        if len(ids) != len(set(ids)):
            errors.append(
                PipelineError(
                    code="extraction.duplicate_claim_id",
                    message="extraction emitted duplicate claim_id values",
                    severity=Severity.HIGH,
                )
            )
        return FactExtractionResult(case_id=ocr.case_id, claims=tuple(claims), errors=tuple(errors))

    def detect_conflicts(self, extraction: FactExtractionResult) -> ConflictDetectionResult:
        by_key: dict[str, list[Claim]] = {}
        for claim in extraction.claims:
            if claim.normalized_key:
                by_key.setdefault(claim.normalized_key, []).append(claim)

        conflicts: list[Conflict] = []
        for key, claims in sorted(by_key.items()):
            values = {claim.normalized_value for claim in claims}
            if len(values) < 2:
                continue
            claim_ids = tuple(sorted({claim.claim_id for claim in claims}))
            if len(claim_ids) < 2:
                continue
            conflicts.append(
                Conflict(
                    conflict_id=f"{extraction.case_id}:conflict:{key}",
                    claim_ids=claim_ids,
                    severity=Severity.HIGH,
                    reason="conflicting values for the same normalized key",
                )
            )
        return ConflictDetectionResult(case_id=extraction.case_id, conflicts=tuple(conflicts))

    def citation_coverage(self, ocr: OCRLayoutResult, extraction: FactExtractionResult) -> CitationCoverageResult:
        known_sources = {(block.source_ref, block.source_type) for block in ocr.blocks}
        covered: list[str] = []
        uncovered: list[str] = []
        for claim in extraction.claims:
            if (claim.source_ref, claim.source_type) in known_sources:
                covered.append(claim.claim_id)
            else:
                uncovered.append(claim.claim_id)
        return CitationCoverageResult(case_id=ocr.case_id, covered_claim_ids=tuple(covered), uncovered_claim_ids=tuple(uncovered))

    def run(self, case: GoldenCase) -> PipelineOutput:
        ocr = self.ocr_layout(case)
        extraction = self.extract_facts(ocr)
        conflicts = self.detect_conflicts(extraction)
        citations = self.citation_coverage(ocr, extraction)
        return PipelineOutput(
            case_id=case.case_id,
            ocr=ocr,
            extraction=extraction,
            conflicts=conflicts,
            citations=citations,
        )
