import unittest

from services.ai.golden_set import synthetic_golden_set
from services.ai.pipeline import DeterministicStubPipeline
from services.ai.provider_pipeline import (
    ModelTelemetry,
    ProviderNeutralPipeline,
    align_source_spans,
)
from services.ai.schema import SourceSpan


class ProviderNeutralPipelineTests(unittest.TestCase):
    def test_full_pipeline_preserves_sources_and_generates_bilingual_questions(self) -> None:
        case = synthetic_golden_set().cases[0]
        result = ProviderNeutralPipeline(DeterministicStubPipeline()).run(case)

        self.assertEqual(len(result.extraction.claims), 2)
        self.assertEqual(len(result.normalized_ocr.blocks), 2)
        self.assertEqual(len(result.span_checks), 2)
        self.assertEqual(result.telemetry.provider, "deterministic-stub")
        self.assertEqual(result.telemetry.model_version, "1")
        self.assertGreater(result.telemetry.input_units, 0)
        self.assertEqual(len(result.doctor_summary.questions), 2)
        self.assertTrue(result.doctor_summary.text_en.startswith("Facts to review:"))
        self.assertTrue(result.doctor_summary.text_zh.startswith("待核对事实："))
        self.assertFalse(result.delivery_blocked)

    def test_conflicts_are_included_in_doctor_questions(self) -> None:
        case = synthetic_golden_set().cases[1]
        result = ProviderNeutralPipeline(DeterministicStubPipeline()).run(case)

        self.assertEqual(len(result.conflicts.conflicts), 1)
        self.assertEqual({question.claim_id for question in result.doctor_summary.questions}, {
            "synthetic-conflict-001",
            "synthetic-conflict-002",
        })
        self.assertTrue(result.delivery_blocked)

    def test_telemetry_can_record_cost_and_latency_without_content(self) -> None:
        case = synthetic_golden_set().cases[0]
        telemetry = ModelTelemetry(
            provider="mock-provider",
            model_version="mock-model@2026-01",
            input_units=12,
            output_units=8,
            cost_usd=0.0042,
            latency_ms=231.5,
        )
        with self.assertRaises(ValueError):
            ProviderNeutralPipeline(DeterministicStubPipeline()).run(case, telemetry=telemetry)

        accepted = ModelTelemetry(
            provider="deterministic-stub",
            model_version="1",
            input_units=12,
            output_units=8,
            cost_usd=0.0042,
            latency_ms=231.5,
        )
        result = ProviderNeutralPipeline(DeterministicStubPipeline()).run(case, telemetry=accepted)
        self.assertEqual(result.telemetry.to_dict()["cost_usd"], 0.0042)
        self.assertEqual(result.telemetry.to_dict()["latency_ms"], 231.5)

    def test_out_of_bounds_span_is_a_delivery_blocker(self) -> None:
        case = synthetic_golden_set().cases[0]
        claims = tuple(
            claim.__class__(
                **{**claim.to_dict(), "source_span": SourceSpan(start=0, end=10_000, page=1)}
            )
            for claim in case.expected_claims
        )
        ocr = DeterministicStubPipeline().ocr_layout(case)
        checks, errors = align_source_spans(ocr, claims)
        self.assertEqual(checks, ())
        self.assertEqual({error.code for error in errors}, {"span.out_of_bounds"})

    def test_telemetry_rejects_negative_and_non_finite_values(self) -> None:
        with self.assertRaises(ValueError):
            ModelTelemetry(provider="provider", model_version="v1", latency_ms=-1)
        with self.assertRaises(ValueError):
            ModelTelemetry(provider="provider", model_version="v1", cost_usd=float("nan"))
