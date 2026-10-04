import unittest
from dataclasses import replace

from services.ai.golden_set import synthetic_golden_set
from services.ai.schema import SourceSpan
from services.ai.staging_worker import (
    StagingAIWorker,
    StagingDocument,
    StagingWorkerRequest,
    aggregate_quality_metrics,
)


class StagingWorkerTests(unittest.TestCase):
    def _request(self, case_index: int = 0, *, key: str = "stage-001") -> StagingWorkerRequest:
        case = synthetic_golden_set().cases[case_index]
        return StagingWorkerRequest(
            document=StagingDocument(
                case_id=case.case_id,
                source_ref=case.document_source_ref,
                source_type=case.document_source_type,
                normalized_ocr_text=case.document_text,
                data_classification=case.data_classification,
            ),
            idempotency_key=key,
        )

    def test_normalized_ocr_produces_existing_extraction_and_summary_artifacts(self) -> None:
        worker = StagingAIWorker()
        result = worker.process(self._request())

        self.assertEqual(result.pipeline.case_id, "synthetic-medication")
        self.assertEqual(len(result.extraction.claims), 2)
        self.assertEqual(len(result.doctor_summary.claim_ids), 2)
        self.assertEqual(result.pipeline.telemetry.provider, "deterministic-stub")
        self.assertFalse(result.delivery_blocked)
        self.assertEqual(result.metrics.case_count, 1)
        self.assertEqual(result.metrics.claim_count, 2)
        self.assertEqual(result.metrics.low_confidence_rate, 0.0)
        self.assertEqual(result.metrics.missing_source_rate, 0.0)
        self.assertEqual(result.metrics.manual_review_rate, 1.0)
        self.assertEqual(result.metrics.confirmation_block_rate, 0.0)

    def test_low_confidence_and_missing_source_block_confirmation(self) -> None:
        case = synthetic_golden_set().cases[0]
        first = case.expected_claims[0].to_dict()
        first["confidence"] = 0.4
        first["source_span"] = None
        second = case.expected_claims[1].to_dict()
        document = "\n".join(
            [
                "FACT\t" + __import__("json").dumps(first, ensure_ascii=False),
                "FACT\t" + __import__("json").dumps(second, ensure_ascii=False),
            ]
        )
        request = StagingWorkerRequest(
            document=StagingDocument(
                case_id="synthetic-gate",
                source_ref=case.document_source_ref,
                source_type=case.document_source_type,
                normalized_ocr_text=document,
            ),
            idempotency_key="stage-gate",
        )
        result = StagingAIWorker().process(request)

        self.assertEqual(result.metrics.low_confidence_claim_count, 1)
        self.assertEqual(result.metrics.missing_source_claim_count, 1)
        self.assertEqual(result.metrics.confirmation_block_case_count, 1)
        self.assertEqual(result.metrics.confirmation_block_rate, 1.0)
        self.assertTrue(result.delivery_blocked)

    def test_conflicts_and_manual_review_are_counted(self) -> None:
        result = StagingAIWorker().process(self._request(1, key="stage-conflict"))

        self.assertEqual(result.metrics.conflict_case_count, 1)
        self.assertEqual(result.metrics.conflict_claim_count, 2)
        self.assertEqual(result.metrics.manual_review_claim_count, 2)
        self.assertEqual(result.metrics.manual_review_rate, 1.0)
        self.assertEqual(result.metrics.confirmation_block_rate, 1.0)
        self.assertTrue(result.delivery_blocked)

    def test_idempotency_returns_same_result_and_rejects_key_reuse(self) -> None:
        worker = StagingAIWorker()
        first = worker.process(self._request(key="same-key"))
        second = worker.process(self._request(key="same-key"))
        self.assertIs(first, second)

        other = self._request(1, key="same-key")
        with self.assertRaises(ValueError):
            worker.process(other)

    def test_content_fingerprint_is_deterministic_and_payload_is_redacted(self) -> None:
        request = self._request(key="")
        self.assertEqual(request.cache_key, request.document.fingerprint)
        result = StagingAIWorker().process(request)
        payload = result.to_dict()
        self.assertEqual(payload["idempotency_key"], request.document.fingerprint)
        self.assertNotIn("normalized_ocr_text", str(payload))
        self.assertNotIn("text_en", str(payload["metrics"]))

    def test_metric_aggregation_uses_claim_and_case_denominators(self) -> None:
        worker = StagingAIWorker()
        first = worker.process(self._request(0, key="aggregate-1"))
        second = worker.process(self._request(1, key="aggregate-2"))
        metrics = aggregate_quality_metrics((first, second))

        self.assertEqual(metrics.case_count, 2)
        self.assertEqual(metrics.claim_count, 4)
        self.assertEqual(metrics.conflict_rate, 0.5)
        self.assertEqual(metrics.confirmation_block_rate, 0.5)
        self.assertEqual(metrics.manual_review_rate, 1.0)

    def test_invalid_threshold_and_classification_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            StagingAIWorker(low_confidence_threshold=1.1)
        with self.assertRaises(ValueError):
            StagingDocument(
                case_id="x",
                source_ref="ref",
                source_type="type",
                normalized_ocr_text="FACT\t{}",
                data_classification="real",
            )


if __name__ == "__main__":
    unittest.main()
