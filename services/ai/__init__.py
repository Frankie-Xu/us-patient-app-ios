"""Auditable AI evaluation boundary.

This package intentionally contains no model-provider integrations.  The
deterministic pipeline is a contract and test double for future OCR and
extraction implementations.
"""

from .golden_set import load_golden_set, synthetic_golden_set
from .pipeline import (
    CitationCoverageResult,
    ConflictDetectionResult,
    DeterministicStubPipeline,
    EvaluationPipeline,
    FactExtractionResult,
    OCRLayoutResult,
    PipelineError,
    PipelineOutput,
)
from .reporting import RegressionReport, evaluate_golden_set
from .schema import (
    Claim,
    Conflict,
    GoldenCase,
    GoldenSet,
    ReviewStatus,
    Severity,
)

__all__ = [
    "Claim",
    "CitationCoverageResult",
    "Conflict",
    "ConflictDetectionResult",
    "DeterministicStubPipeline",
    "EvaluationPipeline",
    "FactExtractionResult",
    "GoldenCase",
    "GoldenSet",
    "OCRLayoutResult",
    "PipelineError",
    "PipelineOutput",
    "RegressionReport",
    "ReviewStatus",
    "Severity",
    "evaluate_golden_set",
    "load_golden_set",
    "synthetic_golden_set",
]
