"""Auditable AI evaluation boundary.

This package intentionally contains no model-provider integrations.  The
deterministic pipeline is a contract and test double for future OCR and
extraction implementations.
"""

from .golden_set import load_golden_set, synthetic_golden_set
from .doctor_view import (
    GATE_SCHEMA,
    GATE_SCHEMA_VERSION,
    DoctorViewDecision,
    DoctorViewErrorCategory,
    DoctorViewGateResult,
    evaluate_doctor_view,
)
from .doctor_brief import (
    BRIEF_SCHEMA,
    BRIEF_SCHEMA_VERSION,
    DoctorBrief,
    DoctorBriefBlocked,
    DoctorBriefScope,
    DoctorBriefTask,
    project_doctor_brief,
)
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

from .provider_pipeline import (
    DoctorQuestion,
    DoctorSummary,
    ModelTelemetry,
    ProviderNeutralPipeline,
    ProviderPipelineResult,
    SourceSpanCheck,
    TelemetrySummary,
    summarize_telemetry,
    align_source_spans,
    normalize_ocr_layout,
)

from .staging_worker import (\n    StagingAIWorker,\n    StagingDocument,\n    StagingQualityMetrics,\n    StagingWorkerRequest,\n    StagingWorkerResult,\n    aggregate_quality_metrics,\n)\n\nfrom .route_compatibility import (
    RouteCompatibilityError,
    RouteCompatibilityReport,
    projection_to_route_payload,
    validate_fact_create_payload,
    validate_fact_review_payload,
    validate_route_json,
    validate_route_payload,
)
from .reporting import RegressionReport, evaluate_golden_set
from .regression_report import (
    REPORT_SCHEMA,
    REPORT_SCHEMA_VERSION,
    GoldenSetRegressionReport,
    generate_regression_report,
    generate_regression_report_from_json,
)
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
    "DoctorViewDecision",
    "DoctorViewErrorCategory",
    "DoctorViewGateResult",
    "DoctorBrief",
    "DoctorBriefBlocked",
    "DoctorBriefScope",
    "DoctorBriefTask",
    "ErrorCategory",
    "EvaluationPipeline",
    "FactExtractionResult",
    "FactCreate",
    "FactReview",
    "GoldenCase",
    "GoldenSet",
    "GATE_SCHEMA",
    "GATE_SCHEMA_VERSION",
    "BRIEF_SCHEMA",
    "BRIEF_SCHEMA_VERSION",
    "ExtractionEvaluation",
    "ExtractionMetrics",
    "MockPredictionVariant",
    "OCRLayoutResult",
    "PipelineError",
    "PipelineOutput",
    "RegressionReport",
    "GoldenSetRegressionReport",
    "DoctorQuestion",
    "DoctorSummary",
    "ModelTelemetry",
    "ProviderNeutralPipeline",
    "ProviderPipelineResult",
    "SourceSpanCheck",
    "TelemetrySummary",
    "REPORT_SCHEMA",
    "REPORT_SCHEMA_VERSION",
    "StagingAIWorker",\n    "StagingDocument",\n    "StagingQualityMetrics",\n    "StagingWorkerRequest",\n    "StagingWorkerResult",\n    "aggregate_quality_metrics",\n    "RouteCompatibilityError",
    "RouteCompatibilityReport",
    "ReviewStatus",
    "ReviewDecision",
    "Severity",
    "SourceSpan",
    "evaluate_golden_set",
    "evaluate_extraction_output",
    "fixed_mock_predictions",
    "project_evaluation",
    "projection_to_route_payload",
    "validate_fact_create_payload",
    "validate_fact_review_payload",
    "validate_route_json",
    "validate_route_payload",
    "load_golden_set",
    "generate_regression_report",
    "generate_regression_report_from_json",
    "evaluate_doctor_view",
    "project_doctor_brief",
    "synthetic_golden_set",
    "align_source_spans",
    "normalize_ocr_layout",
    "summarize_telemetry",
]
