"""Durable local staging processing pipeline.

The worker reads bytes from object storage, performs explicit local text
extraction, and invokes the existing deterministic staging AI adapter. Claims
are persisted as unreviewed facts; the adapter's review gate prevents a
summary from being presented as confirmed data.
"""
from __future__ import annotations

import os
import subprocess
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from services.ai.staging_adapter import StagingAdapter, StagingInput, StagingOutput

from .dependencies import DependencyUnavailableError, ObjectStore
from .models import AuditEvent, Document, DocumentStatus, Fact, JobStatus, JobType, SourceType, UploadProcessingJob, UploadSession, UploadStatus, utc_now
from .store import MetadataStore, NotFoundError


class ProcessingError(RuntimeError):
    """A retryable or terminal processing error without payload text."""

    def __init__(self, code: str, *, retryable: bool = True) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class TextExtraction:
    text: str
    mode: str
    provider: str


@dataclass(frozen=True)
class ProcessingResult:
    job_id: str
    document_id: str
    ocr_mode: str
    claim_count: int
    review_required_count: int
    summary_status: str
    delivery_blocked: bool


def _run_command(command: list[str], content: bytes) -> str:
    try:
        completed = subprocess.run(command, input=content, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True, timeout=30)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ProcessingError("OCR_PROVIDER_UNAVAILABLE") from exc
    text = completed.stdout.decode("utf-8", errors="replace").strip()
    if not text:
        raise ProcessingError("OCR_EMPTY_RESULT", retryable=False)
    return text


def extract_text(content: bytes, media_type: str, *, filename: str = "") -> TextExtraction:
    """Extract text and label the actual local provider used.

    Plain text is a fixture ingest, not an OCR success. PDF and image inputs
    require the corresponding local binary; absence is reported explicitly.
    """
    if not isinstance(content, bytes) or not content:
        raise ProcessingError("OCR_EMPTY_INPUT", retryable=False)
    normalized_type = (media_type or "").lower().split(";", 1)[0].strip()
    if normalized_type.startswith("text/") or normalized_type in {"application/json", "application/x-ndjson"}:
        try:
            text = content.decode("utf-8", errors="strict").strip()
        except UnicodeDecodeError as exc:
            raise ProcessingError("OCR_DECODE_FAILED", retryable=False) from exc
        if not text:
            raise ProcessingError("OCR_EMPTY_RESULT", retryable=False)
        return TextExtraction(text=text, mode="fixture-text-ingest", provider="local-text")
    if normalized_type == "application/pdf" or filename.lower().endswith(".pdf"):
        return TextExtraction(_run_command(["pdftotext", "-layout", "-", "-"], content), "local-pdftotext", "poppler-pdftotext")
    if normalized_type.startswith("image/") or Path(filename).suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        return TextExtraction(_run_command(["tesseract", "stdin", "stdout", "-l", os.getenv("WORKER_TESSERACT_LANG", "eng")], content), "local-tesseract", "tesseract")
    raise ProcessingError("OCR_PROVIDER_UNAVAILABLE", retryable=False)


class WorkerPipeline:
    """Process one persisted API job with durable, idempotent side effects."""

    def __init__(self, store: MetadataStore, object_store: ObjectStore, *, adapter: StagingAdapter | None = None, ocr_provider: Callable[..., str] | None = None, ocr_provider_name: str = "", clock: Callable[[], datetime] = utc_now, data_classification: str = "deidentified") -> None:
        if data_classification not in {"synthetic", "deidentified"}:
            raise ValueError("worker data classification must be synthetic or deidentified")
        self.store = store
        self.object_store = object_store
        self.adapter = adapter or StagingAdapter()
        self.ocr_provider = ocr_provider
        self.ocr_provider_name = ocr_provider_name
        self.clock = clock
        self.data_classification = data_classification

    def _sessions_for(self, document_id: str) -> list[UploadSession]:
        return [session for session in self.store.list_resources("upload_sessions") if session.document_id == document_id]

    def _verified_session(self, document_id: str) -> UploadSession:
        sessions = [session for session in self._sessions_for(document_id) if session.status == UploadStatus.VERIFIED and session.object_key]
        if not sessions:
            raise ProcessingError("UPLOAD_NOT_VERIFIED")
        return max(sessions, key=lambda session: (session.created_at, session.id))

    def _audit(self, job: UploadProcessingJob, action: str, **metadata: str) -> None:
        values = {str(key): str(value) for key, value in metadata.items() if str(value)}
        self.store.append_audit(AuditEvent(id=str(uuid.uuid4()), actor_id="staging-worker", action=action, resource_type="upload_processing_job", resource_id=job.id, request_id=f"worker-{job.id}", occurred_at=self.clock(), metadata=values))

    def _save_job(self, job: UploadProcessingJob, *, status: JobStatus, error_code: str | None = None) -> UploadProcessingJob:
        updated = replace(job, status=status, attempt=job.attempt + (1 if status == JobStatus.RUNNING else 0), error_code=error_code, updated_at=self.clock())
        self.store.save_resource("jobs", updated)
        return updated

    def _set_document_status(self, document: Document, status: DocumentStatus) -> Document:
        if document.status == status:
            return document
        updated = replace(document, status=status, version=document.version + 1, updated_at=self.clock())
        return self.store.save_resource("documents", updated, expected_version=document.version)

    def _persist_claims(self, job: UploadProcessingJob, output: StagingOutput) -> int:
        existing = {fact.id for fact in self.store.list_resources("facts")}
        count = 0
        for claim in output.pipeline.extraction.claims:
            fact_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"patient-app:fact:{job.document_id}:{claim.claim_id}"))
            if fact_id in existing:
                continue
            fact = Fact(id=fact_id, owner_id=job.owner_id, label=claim.normalized_key or claim.claim_id, value=f"{claim.text_en} | {claim.text_zh}", source_ref=claim.source_ref, source_type=SourceType.AI_EXTRACTION, confidence=claim.confidence, document_id=job.document_id, created_at=self.clock(), updated_at=self.clock())
            self.store.save_resource("facts", fact)
            existing.add(fact_id)
            count += 1
        return count

    def process(self, job_id: str) -> ProcessingResult:
        job = self.store.get_resource("jobs", job_id)
        if not isinstance(job, UploadProcessingJob):
            raise ProcessingError("JOB_INVALID", retryable=False)
        if job.status == JobStatus.SUCCEEDED:
            facts = [fact for fact in self.store.list_resources("facts") if fact.document_id == job.document_id]
            return ProcessingResult(job.id, job.document_id, "already-processed", len(facts), sum(f.review_status.value != "confirmed" for f in facts), "blocked", True)
        if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            raise ProcessingError("JOB_NOT_PROCESSABLE", retryable=False)
        running = self._save_job(job, status=JobStatus.RUNNING)
        document = self.store.get_resource("documents", running.document_id)
        try:
            if running.job_type not in {JobType.OCR, JobType.EXTRACT_FACTS, JobType.TRANSLATE}:
                raise ProcessingError("JOB_TYPE_UNSUPPORTED", retryable=False)
            session = self._verified_session(running.document_id)
            source_bytes = self.object_store.get(session.object_key or "")
            if self.ocr_provider is None:
                extraction = extract_text(source_bytes, document.media_type, filename=document.filename)
            else:
                try:
                    text = self.ocr_provider(source_bytes, document.media_type, filename=document.filename)
                except Exception as exc:
                    code = str(getattr(exc, "code", "OCR_PROVIDER_UNAVAILABLE"))
                    retryable = bool(getattr(exc, "retryable", True))
                    raise ProcessingError(code, retryable=retryable) from exc
                extraction = TextExtraction(text=text, mode=self.ocr_provider_name or "provider-ocr", provider=self.ocr_provider_name or "provider")
            output = self.adapter.run(StagingInput(case_id=document.id, source_ref=session.object_key or document.id, source_type="ocr", document_text=extraction.text, data_classification=self.data_classification))
            claim_count = self._persist_claims(running, output)
            self._set_document_status(document, DocumentStatus.READY)
            succeeded = self._save_job(running, status=JobStatus.SUCCEEDED)
            review_required = sum(1 for decision in output.gate.decisions if decision.review_required)
            self._audit(succeeded, "upload_processing.completed", status=succeeded.status.value, ocr_mode=extraction.mode, ocr_provider=extraction.provider, claim_count=str(claim_count), review_required_count=str(review_required), summary_status=output.summary.status, delivery_blocked=str(output.delivery_blocked).lower(), data_classification=self.data_classification)
            return ProcessingResult(succeeded.id, succeeded.document_id, extraction.mode, claim_count, review_required, output.summary.status, output.delivery_blocked)
        except ProcessingError:
            raise
        except (DependencyUnavailableError, NotFoundError, OSError, ValueError) as exc:
            raise ProcessingError("PROCESSING_FAILED") from exc
