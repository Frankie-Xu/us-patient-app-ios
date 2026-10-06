import io
from datetime import datetime, timedelta, timezone

import pytest

from services.api.providers.processing_queue import (
    InMemoryProcessingQueue,
    ProcessingJobStatus,
    QueueIdempotencyConflict,
)
from services.api.providers.s3 import S3ObjectStore, S3ObjectStoreConfig


class FakeS3Client:
    def __init__(self):
        self.objects = {}

    def put_object(self, **kwargs):
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs["Body"]

    def get_object(self, **kwargs):
        return {"Body": io.BytesIO(self.objects[(kwargs["Bucket"], kwargs["Key"])])}


def test_s3_adapter_prefixes_keys_and_round_trips_bytes():
    client = FakeS3Client()
    store = S3ObjectStore(client, S3ObjectStoreConfig(bucket="staging", region="us-east-1"))
    assert store.put("documents/1.bin", b"abc", media_type="application/octet-stream") == "patient-app/documents/1.bin"
    assert store.get("documents/1.bin") == b"abc"


def test_processing_queue_idempotency_and_retry():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    queue = InMemoryProcessingQueue(retry_base_seconds=1)
    first = queue.enqueue(
        owner_id="owner",
        document_id="doc",
        job_type="ocr",
        idempotency_key="request-1",
        payload={"document_id": "doc"},
        now=now,
    )
    assert queue.enqueue(
        owner_id="owner",
        document_id="doc",
        job_type="ocr",
        idempotency_key="request-1",
        payload={"document_id": "doc"},
        now=now,
    ).id == first.id
    with pytest.raises(QueueIdempotencyConflict):
        queue.enqueue(
            owner_id="owner",
            document_id="doc",
            job_type="ocr",
            idempotency_key="request-1",
            payload={"document_id": "other"},
            now=now,
        )

    claimed = queue.claim(worker_id="worker", now=now)
    assert claimed is not None
    assert claimed.status is ProcessingJobStatus.RUNNING
    retrying = queue.fail(claimed.id, error_code="OCR_UNAVAILABLE", now=now)
    assert retrying.status is ProcessingJobStatus.QUEUED
    assert retrying.attempt == 1
    assert queue.claim(worker_id="worker", now=now) is None
    claimed_again = queue.claim(worker_id="worker", now=now + timedelta(seconds=1))
    assert claimed_again is not None
    exhausted = queue.fail(claimed_again.id, error_code="OCR_UNAVAILABLE", now=now + timedelta(seconds=1))
    assert exhausted.status is ProcessingJobStatus.QUEUED
