from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from services.api.dependencies import InMemoryObjectStore
from services.api.models import (
    Document,
    DocumentStatus,
    JobStatus,
    JobType,
    SourceType,
    UploadProcessingJob,
    UploadSession,
    UploadStatus,
)
from services.api.provider_adapters import RedisJobQueue
from services.api.store import InMemoryStore
from services.api.worker_pipeline import ProcessingError, WorkerPipeline, extract_text


NOW = datetime(2030, 1, 2, tzinfo=timezone.utc)


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    def ping(self) -> bool:
        return True

    def set(self, key: str, value: str, *, nx: bool = False) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def delete(self, key: str) -> int:
        return int(self.values.pop(key, None) is not None)

    def rpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        values = self.lists.get(key, [])
        return values[start : None if end == -1 else end + 1]

    def brpoplpush(self, source: str, destination: str, timeout: int) -> str | None:
        del timeout
        values = self.lists.get(source, [])
        if not values:
            return None
        value = values.pop()
        self.lists.setdefault(destination, []).insert(0, value)
        return value

    def lrem(self, key: str, count: int, value: str) -> int:
        del count
        values = self.lists.get(key, [])
        try:
            values.remove(value)
        except ValueError:
            return 0
        return 1

    def scan_iter(self, *, match: str):
        prefix = match.removesuffix("*")
        return iter([key for key in self.values if key.startswith(prefix)])


class WorkerPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryStore()
        self.objects = InMemoryObjectStore()
        self.document = Document(
            id="doc-synthetic",
            owner_id="patient-synthetic",
            filename="record.txt",
            media_type="text/plain",
            size_bytes=95,
            sha256="0" * 64,
            status=DocumentStatus.PROCESSING,
            created_at=NOW,
            updated_at=NOW,
        )
        self.store.save_resource("documents", self.document)
        content = ('FACT\t{"claim_id":"claim-bp","text_en":"Blood pressure is stable",'
                   '"text_zh":"Blood pressure stable","source_ref":"record:line-1",'
                   '"source_type":"ocr","confidence":0.96,"normalized_key":"blood_pressure",'
                   '"normalized_value":"stable","review_status":"needs_review",'
                   '"source_span":{"start":0,"end":10,"page":1}}').encode()
        self.objects.put("uploads/session-synthetic", content, media_type="text/plain")
        session = UploadSession(
            id="session-synthetic",
            owner_id="patient-synthetic",
            document_id=self.document.id,
            document_version=self.document.version,
            size_bytes=len(content),
            sha256=__import__("hashlib").sha256(content).hexdigest(),
            media_type="text/plain",
            expires_at=NOW,
            created_at=NOW,
            status=UploadStatus.VERIFIED,
            verified_at=NOW,
            object_key="uploads/session-synthetic",
        )
        self.store.save_resource("upload_sessions", session)
        self.job = UploadProcessingJob(
            id="job-synthetic",
            owner_id="patient-synthetic",
            document_id=self.document.id,
            job_type=JobType.OCR,
            idempotency_key="job-key",
            created_at=NOW,
            updated_at=NOW,
        )
        self.store.save_resource("jobs", self.job)

    def test_fixture_text_pipeline_persists_unreviewed_claim_and_is_idempotent(self) -> None:
        pipeline = WorkerPipeline(self.store, self.objects, clock=lambda: NOW)
        result = pipeline.process(self.job.id)
        self.assertEqual(result.ocr_mode, "fixture-text-ingest")
        self.assertEqual(result.claim_count, 1)
        self.assertEqual(result.summary_status, "blocked")
        self.assertTrue(result.delivery_blocked)
        self.assertEqual(self.store.get_resource("jobs", self.job.id).status, JobStatus.SUCCEEDED)
        self.assertEqual(self.store.get_resource("documents", self.document.id).status, DocumentStatus.READY)
        facts = self.store.list_resources("facts")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].source_type, SourceType.AI_EXTRACTION)
        self.assertEqual(facts[0].review_status.value, "unreviewed")
        replay = pipeline.process(self.job.id)
        self.assertEqual(replay.ocr_mode, "already-processed")
        self.assertEqual(len(self.store.list_resources("facts")), 1)

    def test_pdf_without_local_provider_is_explicitly_blocked(self) -> None:
        with self.assertRaises(ProcessingError) as caught:
            extract_text(b"not-a-pdf", "application/pdf", filename="record.pdf")
        self.assertIn(caught.exception.code, {"OCR_PROVIDER_UNAVAILABLE", "OCR_EMPTY_RESULT"})


class RedisLeaseTests(unittest.TestCase):
    def test_claim_ack_and_retry_are_durable(self) -> None:
        client = _FakeRedis()
        queue = RedisJobQueue("redis://local", client=client, queue_name="jobs")
        queue.enqueue("job-1", {"document_id": "doc-1", "job_type": "ocr"})
        claimed = queue.claim(block_seconds=0, lease_seconds=30)
        self.assertIsNotNone(claimed)
        assert claimed is not None
        queue.requeue(claimed)
        self.assertEqual(queue.entries, [("job-1", {"document_id": "doc-1", "job_type": "ocr"})])
        claimed = queue.claim(block_seconds=0, lease_seconds=30)
        assert claimed is not None
        queue.ack(claimed)
        self.assertEqual(queue.entries, [])
        self.assertIn("jobs:job:job-1", client.values)

    def test_expired_lease_is_recovered_once(self) -> None:
        client = _FakeRedis()
        queue = RedisJobQueue("redis://local", client=client, queue_name="jobs")
        queue.enqueue("job-2", {"document_id": "doc-2", "job_type": "ocr"})
        with patch("services.api.provider_adapters.time.time", return_value=100.0):
            claimed = queue.claim(block_seconds=0, lease_seconds=10)
        assert claimed is not None
        with patch("services.api.provider_adapters.time.time", return_value=111.0):
            self.assertEqual(queue.recover_stale(lease_seconds=10), 1)
            self.assertEqual(queue.recover_stale(lease_seconds=10), 0)
        self.assertEqual(queue.entries, [("job-2", {"document_id": "doc-2", "job_type": "ocr"})])


if __name__ == "__main__":
    unittest.main()
