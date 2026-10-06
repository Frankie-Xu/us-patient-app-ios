"""Provider-neutral processing queue with retry and idempotency semantics.

The in-memory implementation is suitable for contract tests and staging
rehearsals. The PostgreSQL migration in this change provides the durable schema
for a worker adapter using row locking; no queue provider or credential is
selected here.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Mapping, Protocol


class ProcessingJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProcessingQueueError(RuntimeError):
    pass


class QueueIdempotencyConflict(ProcessingQueueError):
    pass


@dataclass(frozen=True)
class ProcessingJob:
    id: str
    owner_id: str
    document_id: str
    job_type: str
    idempotency_key: str
    request_hash: str
    status: ProcessingJobStatus
    attempt: int
    max_attempts: int
    next_attempt_at: datetime
    locked_by: str | None = None
    locked_at: datetime | None = None
    error_code: str | None = None
    created_at: datetime = datetime.min.replace(tzinfo=timezone.utc)
    updated_at: datetime = datetime.min.replace(tzinfo=timezone.utc)


class ProcessingQueue(Protocol):
    def is_ready(self) -> bool:
        ...

    def enqueue(
        self,
        *,
        owner_id: str,
        document_id: str,
        job_type: str,
        idempotency_key: str,
        payload: Mapping[str, str],
        max_attempts: int = 3,
        now: datetime | None = None,
    ) -> ProcessingJob:
        ...

    def claim(self, *, worker_id: str, now: datetime | None = None) -> ProcessingJob | None:
        ...

    def complete(self, job_id: str, *, now: datetime | None = None) -> ProcessingJob:
        ...

    def fail(self, job_id: str, *, error_code: str, now: datetime | None = None) -> ProcessingJob:
        ...

    def get(self, job_id: str) -> ProcessingJob:
        ...


class InMemoryProcessingQueue:
    def __init__(self, *, available: bool = True, retry_base_seconds: int = 5) -> None:
        if retry_base_seconds < 1:
            raise ValueError("retry_base_seconds must be positive")
        self.available = available
        self.retry_base_seconds = retry_base_seconds
        self._jobs: dict[str, ProcessingJob] = {}
        self._idempotency: dict[tuple[str, str], tuple[str, str]] = {}

    def is_ready(self) -> bool:
        return self.available

    def _now(self, now: datetime | None) -> datetime:
        value = now or datetime.now(timezone.utc)
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("queue time must include a timezone")
        return value

    def _ensure_ready(self) -> None:
        if not self.available:
            raise ProcessingQueueError("processing queue is unavailable")

    @staticmethod
    def _hash_payload(payload: Mapping[str, str]) -> str:
        canonical = json.dumps({str(k): str(v) for k, v in payload.items()}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def enqueue(
        self,
        *,
        owner_id: str,
        document_id: str,
        job_type: str,
        idempotency_key: str,
        payload: Mapping[str, str],
        max_attempts: int = 3,
        now: datetime | None = None,
    ) -> ProcessingJob:
        self._ensure_ready()
        if not all(isinstance(value, str) and value.strip() for value in (owner_id, document_id, job_type, idempotency_key)):
            raise ValueError("queue identifiers must be non-empty")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        timestamp = self._now(now)
        request_hash = self._hash_payload(payload)
        idempotency_key_tuple = (owner_id, idempotency_key)
        existing_key = self._idempotency.get(idempotency_key_tuple)
        if existing_key is not None:
            existing_id, existing_hash = existing_key
            if existing_hash != request_hash:
                raise QueueIdempotencyConflict("idempotency key was reused with a different payload")
            return self._jobs[existing_id]
        job = ProcessingJob(
            id=str(uuid.uuid4()),
            owner_id=owner_id,
            document_id=document_id,
            job_type=job_type,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            status=ProcessingJobStatus.QUEUED,
            attempt=0,
            max_attempts=max_attempts,
            next_attempt_at=timestamp,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._jobs[job.id] = job
        self._idempotency[idempotency_key_tuple] = (job.id, request_hash)
        return job

    def claim(self, *, worker_id: str, now: datetime | None = None) -> ProcessingJob | None:
        self._ensure_ready()
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        timestamp = self._now(now)
        candidates = sorted(
            (
                job for job in self._jobs.values()
                if job.status == ProcessingJobStatus.QUEUED and job.next_attempt_at <= timestamp
            ),
            key=lambda job: (job.next_attempt_at, job.created_at, job.id),
        )
        if not candidates:
            return None
        job = candidates[0]
        claimed = replace(
            job,
            status=ProcessingJobStatus.RUNNING,
            attempt=job.attempt + 1,
            locked_by=worker_id,
            locked_at=timestamp,
            updated_at=timestamp,
            error_code=None,
        )
        self._jobs[job.id] = claimed
        return claimed

    def get(self, job_id: str) -> ProcessingJob:
        self._ensure_ready()
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise KeyError("processing job not found") from exc

    def complete(self, job_id: str, *, now: datetime | None = None) -> ProcessingJob:
        self._ensure_ready()
        timestamp = self._now(now)
        job = self.get(job_id)
        if job.status in (ProcessingJobStatus.SUCCEEDED, ProcessingJobStatus.CANCELLED):
            return job
        if job.status != ProcessingJobStatus.RUNNING:
            raise ProcessingQueueError("only running jobs can complete")
        completed = replace(job, status=ProcessingJobStatus.SUCCEEDED, locked_by=None, locked_at=None, updated_at=timestamp)
        self._jobs[job_id] = completed
        return completed

    def fail(self, job_id: str, *, error_code: str, now: datetime | None = None) -> ProcessingJob:
        self._ensure_ready()
        if not error_code.strip():
            raise ValueError("error_code is required")
        timestamp = self._now(now)
        job = self.get(job_id)
        if job.status in (ProcessingJobStatus.SUCCEEDED, ProcessingJobStatus.CANCELLED):
            return job
        if job.status != ProcessingJobStatus.RUNNING:
            raise ProcessingQueueError("only running jobs can fail")
        exhausted = job.attempt >= job.max_attempts
        failed = replace(
            job,
            status=ProcessingJobStatus.FAILED if exhausted else ProcessingJobStatus.QUEUED,
            next_attempt_at=timestamp + timedelta(seconds=self.retry_base_seconds * (2 ** max(job.attempt - 1, 0))),
            locked_by=None,
            locked_at=None,
            error_code=error_code,
            updated_at=timestamp,
        )
        self._jobs[job_id] = failed
        return failed
