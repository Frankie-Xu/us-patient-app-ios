from __future__ import annotations

import unittest

from services.api.models import Document, DocumentStatus, JobStatus, JobType, UploadProcessingJob
from scripts.staging.worker import retry_backoff_seconds
from scripts.staging.worker import WorkerRuntime


class _RetryStore:
    def __init__(self, document: Document) -> None:
        self.resources = {("documents", document.id): document}

    def save_resource(self, resource_type, value, expected_version=None):
        if expected_version is not None:
            current = self.resources[(resource_type, value.id)]
            if current.version != expected_version:
                raise AssertionError("unexpected version")
        self.resources[(resource_type, value.id)] = value
        return value

    def get_resource(self, resource_type, identifier):
        return self.resources[(resource_type, identifier)]


class WorkerRetryPolicyTests(unittest.TestCase):
    def test_retry_backoff_is_bounded_and_exponential(self) -> None:
        self.assertEqual(retry_backoff_seconds(0, 1), 0.0)
        self.assertEqual(retry_backoff_seconds(1, 1), 1.0)
        self.assertEqual(retry_backoff_seconds(1, 2), 2.0)
        self.assertEqual(retry_backoff_seconds(1, 4), 8.0)
        self.assertEqual(retry_backoff_seconds(10, 10), 30.0)

    def test_invalid_attempts_do_not_delay(self) -> None:
        self.assertEqual(retry_backoff_seconds(2, 0), 0.0)
        self.assertEqual(retry_backoff_seconds(-1, 1), 0.0)

    def test_terminal_error_fails_job_without_requeue(self) -> None:
        document = Document(id="doc", owner_id="owner", filename="fixture.txt", media_type="text/plain", size_bytes=1, sha256="0" * 64, status=DocumentStatus.PROCESSING)
        store = _RetryStore(document)
        runtime = object.__new__(WorkerRuntime)
        runtime.store = store
        runtime.max_attempts = 3
        job = UploadProcessingJob(id="job", owner_id="owner", document_id="doc", job_type=JobType.OCR, idempotency_key="key", status=JobStatus.RUNNING, attempt=1)
        self.assertFalse(runtime._mark_retry(job, "OCR_PROVIDER_REJECTED", retryable=False))
        self.assertEqual(store.resources[("jobs", "job")].status, JobStatus.FAILED)
        self.assertEqual(store.resources[("documents", "doc")].status, DocumentStatus.FAILED)

    def test_retryable_error_stops_at_max_attempts(self) -> None:
        document = Document(id="doc", owner_id="owner", filename="fixture.txt", media_type="text/plain", size_bytes=1, sha256="0" * 64, status=DocumentStatus.PROCESSING)
        store = _RetryStore(document)
        runtime = object.__new__(WorkerRuntime)
        runtime.store = store
        runtime.max_attempts = 2
        first = UploadProcessingJob(id="job-1", owner_id="owner", document_id="doc", job_type=JobType.OCR, idempotency_key="key-1", status=JobStatus.RUNNING, attempt=1)
        self.assertTrue(runtime._mark_retry(first, "OCR_PROVIDER_RETRYABLE", retryable=True))
        self.assertEqual(store.resources[("jobs", "job-1")].status, JobStatus.QUEUED)
        second = UploadProcessingJob(id="job-2", owner_id="owner", document_id="doc", job_type=JobType.OCR, idempotency_key="key-2", status=JobStatus.RUNNING, attempt=2)
        self.assertFalse(runtime._mark_retry(second, "OCR_PROVIDER_RETRYABLE", retryable=True))
        self.assertEqual(store.resources[("jobs", "job-2")].status, JobStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
