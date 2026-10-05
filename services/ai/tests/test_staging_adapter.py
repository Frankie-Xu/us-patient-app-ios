import json
import unittest
from pathlib import Path

from services.ai.staging_adapter import (
    ADAPTER_SCHEMA,
    ADAPTER_SCHEMA_VERSION,
    DeterministicSummaryProvider,
    StagingAdapter,
    StagingInput,
    load_staging_inputs,
    normalize_ocr_text,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "staging_adapter_input.json"


class StagingAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inputs = load_staging_inputs(FIXTURE)
        self.clean, self.low_confidence, self.conflict = self.inputs
        ticks = iter((100.0, 100.025, 100.050, 100.075, 100.100, 100.125))
        self.adapter = StagingAdapter(clock=lambda: next(ticks), cost_usd=0.012)

    def test_fixture_is_bilingual_deidentified_and_strict(self) -> None:
        self.assertEqual(len(self.inputs), 3)
        self.assertTrue(all(item.data_classification == "deidentified" for item in self.inputs))
        self.assertTrue(all(item.language == "bilingual" for item in self.inputs))
        with self.assertRaises(ValueError):
            StagingInput.from_dict({**self.clean.__dict__, "unexpected": True})

    def test_ocr_normalization_is_repeatable_and_keeps_fact_delimiter(self) -> None:
        raw = "\u00a0 Example   OCR \r\n\r\n FACT\t {\"value\": 1}  \n"
        expected = "Example OCR\n\nFACT\t{\"value\": 1}"
        self.assertEqual(normalize_ocr_text(raw), expected)
        self.assertEqual(normalize_ocr_text(raw), normalize_ocr_text(raw))

    def test_clean_case_requires_explicit_review_before_summary(self) -> None:
        output = self.adapter.run(self.clean)

        self.assertEqual(output.case_id, "staging-bilingual-clean")
        self.assertEqual(output.metadata.model_provider, "deterministic-stub")
        self.assertEqual(output.gate.auto_confirmed_claim_ids, ())
        self.assertEqual(len(output.gate.review_required_claim_ids), 2)
        self.assertTrue(output.delivery_blocked)
        self.assertEqual(output.summary.status, "blocked")
        self.assertEqual(output.metadata.cost_usd, 0.012)
        self.assertAlmostEqual(output.metadata.latency_ms, 25.0, places=6)
        self.assertEqual(output.to_dict()["adapter_schema"], ADAPTER_SCHEMA)
        self.assertEqual(output.to_dict()["schema_version"], ADAPTER_SCHEMA_VERSION)

        confirmed = self.adapter.run(
            self.clean,
            confirmed_claim_ids=("deid-clean-001", "deid-clean-002"),
        )
        self.assertFalse(confirmed.gate.delivery_blocked)
        self.assertEqual(confirmed.gate.auto_confirmed_claim_ids, ())
        self.assertEqual(confirmed.summary.status, "ready")
        self.assertEqual(set(confirmed.summary.source_claim_ids), {"deid-clean-001", "deid-clean-002"})

    def test_low_confidence_and_missing_source_span_always_block(self) -> None:
        output = self.adapter.run(self.low_confidence, confirmed_claim_ids=("deid-review-001",))

        decision = output.gate.decisions[0]
        self.assertTrue(decision.review_required)
        self.assertFalse(decision.auto_confirmed)
        self.assertIn("staging.low_confidence", decision.reasons)
        self.assertIn("doctor_view.source_span_missing", decision.reasons)
        self.assertEqual(output.summary.status, "blocked")
        self.assertTrue(output.delivery_blocked)

    def test_conflicting_claims_are_not_delivered_after_explicit_review(self) -> None:
        output = self.adapter.run(
            self.conflict,
            confirmed_claim_ids=("deid-conflict-001", "deid-conflict-002"),
        )

        self.assertEqual(len(output.pipeline.conflicts.conflicts), 1)
        self.assertTrue(output.gate.delivery_blocked)
        self.assertEqual(output.gate.error_categories["staging.conflict_detected"], 2)
        self.assertEqual(output.summary.status, "blocked")
        self.assertEqual(output.gate.auto_confirmed_claim_ids, ())

    def test_regression_report_contains_operational_metrics_without_content(self) -> None:
        ticks = iter((200.0, 200.010, 200.020, 200.030, 200.040, 200.050))
        adapter = StagingAdapter(clock=lambda: next(ticks), cost_usd=0.005)
        report = adapter.regression_report(self.inputs, dataset_id="deid-staging", dataset_version="2026.10")
        payload = report.to_dict()

        self.assertEqual(payload["report_schema"], "patient-app-ai/staging-regression-report")
        self.assertEqual(payload["sample_count"], 3)
        self.assertEqual(payload["model_provider"], "deterministic-stub")
        self.assertEqual(payload["model_version"], "1")
        self.assertGreaterEqual(payload["metrics"]["latency_ms_total"], 0.0)
        self.assertEqual(payload["metrics"]["cost_usd_total"], 0.015)
        self.assertTrue(payload["delivery_blocked"])
        self.assertNotIn("Example medication", json.dumps(payload, ensure_ascii=False))

    def test_summary_provider_is_replaceable(self) -> None:
        class RecordingProvider(DeterministicSummaryProvider):
            def __init__(self) -> None:
                self.seen_claim_count = -1

            def generate(self, claims, conflicts, gate):
                selected = tuple(claims)
                self.seen_claim_count = len(selected)
                return super().generate(selected, conflicts, gate)

        provider = RecordingProvider()
        adapter = StagingAdapter(summary_provider=provider, clock=lambda: 1.0)
        output = adapter.run(self.clean)
        self.assertEqual(provider.seen_claim_count, 0)
        self.assertEqual(output.metadata.summary_provider, "deterministic-summary")


if __name__ == "__main__":
    unittest.main()
