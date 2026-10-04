"""Auditable AI evaluation boundary.

This package intentionally contains no model-provider integrations.  The
deterministic pipeline is a contract and test double for future OCR and
extraction implementations.
"""

from .golden_set import load_golden_set, synthetic_golden_set
from .api_projection import (
    API_VERSION,
    ApiProjection,
    ApiReviewStatus,
    FactCreate,
    FactReview,
    project_evaluation,
)
from .mock_predictions import MockPredictionVariant, fixed_mock_predictions
from .output_evaluator import (
    ClassifiedError,
    ErrorCategory,
    ExtractionEvaluation,
    ExtractionMetrics,
    ReviewDecision,
    evaluate_extraction_output,
)
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
    SourceSpan,
)

__all__ = [
    "Claim",
    "API_VERSION",
    "ApiProjection",
    "ApiReviewStatus",
    "ClassifiedError",
    "CitationCoverageResult",
    "Conflict",
    "ConflictDetectionResult",
    "DeterministicStubPipeline",
    "ErrorCategory",
    "EvaluationPipeline",
    "FactExtractionResult",
    "FactCreate",
    "FactReview",
    "GoldenCase",
    "GoldenSet",
    "ExtractionEvaluation",
    "ExtractionMetrics",
    "MockPredictionVariant",
    "OCRLayoutResult",
    "PipelineError",
    "PipelineOutput",
    "RegressionReport",
    "ReviewStatus",
    "ReviewDecision",
    "Severity",
    "SourceSpan",
    "evaluate_golden_set",
    "evaluate_extraction_output",
    "fixed_mock_predictions",
    "project_evaluation",
    "load_golden_set",
    "synthetic_golden_set",
]
