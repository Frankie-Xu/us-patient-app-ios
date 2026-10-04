#!/usr/bin/env python3
"""Deterministic staging resilience smoke scenarios.

The scenarios exercise existing API idempotency and processing-queue seams with
synthetic metadata only. No document bytes are created, persisted, or printed.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from services.api.models import AuthContext, PrincipalRole, Scope  # noqa: E402
from services.api.providers.processing_queue import (  # noqa: E402
    InMemoryProcessingQueue,
    ProcessingJobStatus,
)
from services.api.service import ApiService  # noqa: E402
from services.api.store import IdempotencyConflictError  # noqa: E402

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_FIXED_NOW = datetime(2035, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class SyntheticFileMetadata:
    """A de-identified file descriptor; it deliberately carries no payload."""

    filename: str
    media_type: str
    size_bytes: int
    sha256: str


def _metadata(filename: str, media_type: str, size_bytes: int) -> SyntheticFileMetadata:
    # The digest fingerprints a synthetic label rather than a patient document.
    digest = hashlib.sha256(f"deidentified-fixture:{filename}".encode("utf-8")).hexdigest()
    return SyntheticFileMetadata(filename, media_type, size_bytes, digest)


def validate_file_metadata(metadata: SyntheticFileMetadata) -> None:
    """Validate large PDF/photo metadata at the same bounded API seam."""

    if metadata.media_type not in {"application/pdf", "image/jpeg", "image/png"}:
        raise AssertionError("unsupported synthetic media type")
    if not 1 <= metadata.size_bytes <= _MAX_UPLOAD_BYTES:
        raise AssertionError("synthetic file size outside upload bounds")
    if len(metadata.sha256) != 64 or any(char not in "0123456789abcdef" for char in metadata.sha256):
        raise AssertionError("synthetic checksum shape is invalid")


def _auth() -> AuthContext:
    return AuthContext(
        "synthetic-patient",
        roles=frozenset({PrincipalRole.PATIENT}),
        scopes=frozenset({Scope.DOCUMENTS_READ, Scope.DOCUMENTS_WRITE}),
        request_id="phase37-resilience",
    )


def run_large_file_metadata() -> dict[str, object]:
    """Cover near-limit PDF and photo descriptors without constructing bytes."""

    service = ApiService(clock=lambda: _FIXED_NOW)
    auth = _auth()
    fixtures = (
        _metadata("synthetic-large-report.pdf", "application/pdf", _MAX_UPLOAD_BYTES - 1),
        _metadata("synthetic-large-photo.jpg", "image/jpeg", _MAX_UPLOAD_BYTES - 2048),
    )
    sessions = []
    for index, fixture in enumerate(fixtures):
        validate_file_metadata(fixture)
        document = service.create_document(
            auth,
            filename=fixture.filename,
            media_type=fixture.media_type,
            size_bytes=fixture.size_bytes,
            sha256=fixture.sha256,
            idempotency_key=f"large-file-{index}",
        )
        sessions.append(service.create_upload_session(auth, document_id=document.id, idempotency_key=f"large-session-{index}"))
    assert len(sessions) == 2
    assert all(session.status.value == "pending" for session in sessions)
    return {"files_checked": len(fixtures), "metadata_only": True, "sessions_pending": len(sessions)}


def _poll_status(get_status: Callable[[], ProcessingJobStatus], expected: ProcessingJobStatus) -> list[str]:
    statuses: list[str] = []
    for _ in range(8):
        status = get_status()
        statuses.append(status.value)
        if status is expected:
            return statuses
    raise AssertionError(f"processing state did not reach {expected.value}")


def run_retry_and_polling() -> dict[str, object]:
    """Exercise bounded transient failures, resume timing, and state polling."""

    now = _FIXED_NOW
    queue = InMemoryProcessingQueue(retry_base_seconds=1)
    recovering = queue.enqueue(
        owner_id="synthetic-patient",
        document_id="synthetic-document",
        job_type="ocr",
        idempotency_key="retry-recovery-001",
        payload={"document_id": "synthetic-document", "kind": "ocr"},
        max_attempts=3,
        now=now,
    )
    seen = _poll_status(lambda: queue.get(recovering.id).status, ProcessingJobStatus.QUEUED)
    first = queue.claim(worker_id="synthetic-worker", now=now)
    assert first is not None and first.attempt == 1
    queue.fail(first.id, error_code="TRANSIENT_NETWORK", now=now)
    seen.extend(_poll_status(lambda: queue.get(recovering.id).status, ProcessingJobStatus.QUEUED))
    second = queue.claim(worker_id="synthetic-worker", now=now + timedelta(seconds=1))
    assert second is not None and second.attempt == 2
    queue.fail(second.id, error_code="TRANSIENT_NETWORK", now=now + timedelta(seconds=1))
    third_time = now + timedelta(seconds=3)
    third = queue.claim(worker_id="synthetic-worker", now=third_time)
    assert third is not None and third.attempt == 3
    queue.complete(third.id, now=third_time)
    seen.extend(_poll_status(lambda: queue.get(recovering.id).status, ProcessingJobStatus.SUCCEEDED))
    assert queue.get(recovering.id).attempt == 3

    exhausted = queue.enqueue(
        owner_id="synthetic-patient",
        document_id="synthetic-document-2",
        job_type="ocr",
        idempotency_key="retry-exhausted-001",
        payload={"document_id": "synthetic-document-2", "kind": "ocr"},
        max_attempts=2,
        now=now,
    )
    claimed = queue.claim(worker_id="synthetic-worker", now=now)
    assert claimed is not None
    queue.fail(claimed.id, error_code="TRANSIENT_NETWORK", now=now)
    claimed = queue.claim(worker_id="synthetic-worker", now=now + timedelta(seconds=1))
    assert claimed is not None and claimed.attempt == 2
    queue.fail(claimed.id, error_code="TRANSIENT_NETWORK", now=now + timedelta(seconds=1))
    assert queue.get(exhausted.id).status is ProcessingJobStatus.FAILED
    assert queue.claim(worker_id="synthetic-worker", now=now + timedelta(seconds=30)) is None
    return {
        "recovery_status": queue.get(recovering.id).status.value,
        "recovery_attempts": queue.get(recovering.id).attempt,
        "exhausted_status": queue.get(exhausted.id).status.value,
        "poll_samples": len(seen),
        "bounded": True,
    }


def run_idempotency() -> dict[str, object]:
    """Ensure duplicate content requests replay and conflicting keys fail closed."""

    service = ApiService(clock=lambda: _FIXED_NOW)
    auth = _auth()
    fixture = _metadata("synthetic-duplicate.pdf", "application/pdf", 4096)
    first = service.create_document(
        auth,
        filename=fixture.filename,
        media_type=fixture.media_type,
        size_bytes=fixture.size_bytes,
        sha256=fixture.sha256,
        idempotency_key="duplicate-content-001",
    )
    replay = service.create_document(
        auth,
        filename=fixture.filename,
        media_type=fixture.media_type,
        size_bytes=fixture.size_bytes,
        sha256=fixture.sha256,
        idempotency_key="duplicate-content-001",
    )
    assert replay.id == first.id
    conflict_detected = False
    try:
        service.create_document(
            auth,
            filename="synthetic-different.pdf",
            media_type=fixture.media_type,
            size_bytes=fixture.size_bytes,
            sha256=fixture.sha256,
            idempotency_key="duplicate-content-001",
        )
    except IdempotencyConflictError:
        conflict_detected = True
    assert conflict_detected
    return {"replayed_same_resource": True, "conflicting_payload_rejected": conflict_detected}


def run_all() -> dict[str, object]:
    return {
        "large_file_metadata": run_large_file_metadata(),
        "retry_and_state_polling": run_retry_and_polling(),
        "duplicate_idempotency": run_idempotency(),
    }


def main() -> int:
    scenarios = run_all()
    print(json.dumps({"status": "passed", "synthetic_only": True, "raw_bytes_logged": False, "scenarios": scenarios}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
