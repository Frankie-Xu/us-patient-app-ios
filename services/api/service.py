"""Application service implementing the initial API contract."""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import uuid
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping

from .auth import require_owner, require_role, require_scope
from .dependencies import DependencyUnavailableError, InMemoryJobQueue, InMemoryObjectStore, JobQueue, ObjectStore
from .models import (
    AuditEvent,
    AuthContext,
    Document,
    DocumentStatus,
    Fact,
    IdempotencyRecord,
    JobStatus,
    JobType,
    PrincipalRole,
    ReviewStatus,
    Scope,
    ShareStatus,
    ShareVersion,
    SourceType,
    Task,
    Topic,
    UploadProcessingJob,
    UploadSession,
    UploadStatus,
    Visit,
    utc_now,
)
from .store import IdempotencyConflictError, InMemoryStore, MetadataStore, NotFoundError, VersionConflictError


class ServiceError(RuntimeError):
    pass


class ShareAccessError(ServiceError):
    pass


class UploadSessionError(ServiceError):
    """Operational upload error with a stable, payload-free HTTP envelope."""

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
UPLOAD_SESSION_TTL = timedelta(minutes=15)
_DEPENDENCY_UNSET = object()


class ApiService:
    """Use-case boundary with explicit auth, audit and PHI-safe adapters."""

    def __init__(
        self,
        store: MetadataStore | None | object = _DEPENDENCY_UNSET,
        clock: Callable[[], datetime] = utc_now,
        object_store: ObjectStore | None | object = _DEPENDENCY_UNSET,
        job_queue: JobQueue | None | object = _DEPENDENCY_UNSET,
    ) -> None:
        # Omitted dependencies retain the offline in-memory defaults. Explicit
        # None is preserved so readiness fails closed for misconfigured startup.
        self.store: MetadataStore | None = InMemoryStore() if store is _DEPENDENCY_UNSET else store  # type: ignore[assignment]
        self.clock = clock
        self.object_store: ObjectStore | None = InMemoryObjectStore() if object_store is _DEPENDENCY_UNSET else object_store  # type: ignore[assignment]
        self.job_queue: JobQueue | None = InMemoryJobQueue() if job_queue is _DEPENDENCY_UNSET else job_queue  # type: ignore[assignment]
        # Raw share tokens live only in this process memory for idempotent replay.
        # The store receives only a digest, so a durable adapter never persists a token.
        self._ephemeral_share_tokens: dict[str, str] = {}
        # A checksum replay with a new idempotency key must not race into two
        # metadata records.  Provider-backed stores should enforce the same
        # invariant transactionally; this lock closes the gap for the local
        # service and keeps concurrent requests deterministic in tests.
        self._document_dedupe_lock = threading.RLock()

    def _id(self) -> str:
        return str(uuid.uuid4())

    def readiness(self) -> dict[str, object]:
        checks: dict[str, bool] = {
            "metadata_store": self._dependency_ready(self.store),
            "object_store": self._dependency_ready(self.object_store),
            "job_queue": self._dependency_ready(self.job_queue),
        }
        return {"status": "ready" if all(checks.values()) else "not_ready", "checks": checks}

    @staticmethod
    def _dependency_ready(dependency: MetadataStore | ObjectStore | JobQueue | None) -> bool:
        if dependency is None:
            return False
        try:
            return bool(dependency.is_ready())
        except Exception:
            return False

    def _audit(self, auth: AuthContext, action: str, resource_type: str, resource_id: str, **metadata: str) -> None:
        # Metadata is intentionally scalar and caller-provided; no document text,
        # filenames, claims, tokens or identifiers beyond resource_id are accepted.
        event = AuditEvent(
            id=self._id(),
            actor_id=auth.subject_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=auth.request_id,
            occurred_at=self.clock(),
            metadata={str(k): str(v) for k, v in metadata.items()},
        )
        if self.store is None:
            raise DependencyUnavailableError("metadata store is unavailable")
        self.store.append_audit(event)

    def _idempotent(self, auth: AuthContext, key: str, payload: Mapping[str, Any]) -> Any | None:
        if not key.strip():
            raise ServiceError("Idempotency-Key is required for mutating requests")
        request_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        record = self.store.get_idempotency(auth.subject_id, key)
        if record is None:
            return None
        if record.request_hash != request_hash:
            raise IdempotencyConflictError("idempotency key was already used with a different request")
        return record.response_body

    def _remember(self, auth: AuthContext, key: str, payload: Mapping[str, Any], response: Any, status: int = 200) -> None:
        request_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        self.store.remember_idempotency(IdempotencyRecord(key, auth.subject_id, request_hash, status, {"value": response}))

    def _find_document_by_checksum(self, owner_id: str, *, size_bytes: int, sha256: str) -> Document | None:
        """Return an active document with the same account-scoped content.

        The owner is part of the deduplication boundary: a matching checksum in
        another account must never be observable or reused.  Size is checked as
        a collision guard, while filename and media type remain presentation
        metadata and therefore do not prevent a content replay.  Deleted
        records are excluded so a user can intentionally upload a replacement.
        """
        normalized = sha256.lower()
        for candidate in self.store.list_resources("documents"):
            if not isinstance(candidate, Document) or candidate.owner_id != owner_id:
                continue
            if candidate.status == DocumentStatus.DELETED:
                continue
            if candidate.size_bytes != size_bytes:
                continue
            if candidate.sha256.lower() == normalized:
                return candidate
        return None

    def create_document(
        self,
        auth: AuthContext,
        *,
        filename: str,
        media_type: str,
        size_bytes: int,
        sha256: str,
        idempotency_key: str,
    ) -> Document:
        require_scope(auth, Scope.DOCUMENTS_WRITE)
        # SHA-256 is case-insensitive on the wire but canonicalized here so a
        # retry that changes only hex casing remains the same idempotent request.
        normalized_sha256 = sha256.lower() if isinstance(sha256, str) else sha256
        payload = {"filename": filename, "media_type": media_type, "size_bytes": size_bytes, "sha256": normalized_sha256}
        with self._document_dedupe_lock:
            replay = self._idempotent(auth, idempotency_key, payload)
            if replay is not None:
                return self.store.get_resource("documents", replay["value"]["id"])

            existing = self._find_document_by_checksum(
                auth.subject_id,
                size_bytes=size_bytes,
                sha256=normalized_sha256,
            )
            if existing is not None:
                # Keep a receipt for this new key so subsequent retries are a
                # normal idempotent replay, while leaving the existing resource
                # version and metadata untouched.
                self._audit(auth, "document.deduplicated", "document", existing.id, reason="checksum")
                self._remember(auth, idempotency_key, payload, {"id": existing.id}, status=201)
                return existing

            document = Document(self._id(), auth.subject_id, filename, media_type, size_bytes, normalized_sha256, created_at=self.clock(), updated_at=self.clock())
            self.store.save_resource("documents", document)
            self._audit(auth, "document.created", "document", document.id)
            self._remember(auth, idempotency_key, payload, {"id": document.id}, status=201)
            return document

    def create_upload_session(self, auth: AuthContext, *, document_id: str, idempotency_key: str) -> UploadSession:
        require_scope(auth, Scope.DOCUMENTS_WRITE)
        document = self.store.get_resource("documents", document_id)
        require_owner(auth, document.owner_id)
        payload = {"operation": "create_upload_session", "document_id": document_id}
        replay = self._idempotent(auth, idempotency_key, payload)
        if replay is not None:
            return self.store.get_resource("upload_sessions", replay["value"]["id"])
        if document.status != DocumentStatus.UPLOADED:
            raise UploadSessionError(409, "UPLOAD_SESSION_CONFLICT", "document is not available for upload")
        if document.size_bytes > MAX_UPLOAD_BYTES:
            raise UploadSessionError(413, "UPLOAD_TOO_LARGE", "upload exceeds the supported size limit")
        if document.size_bytes < 1:
            raise UploadSessionError(422, "VALIDATION_ERROR", "upload must contain at least one byte")
        now = self.clock()
        session = UploadSession(self._id(), document.owner_id, document.id, document.version,
                                document.size_bytes, document.sha256.lower(), document.media_type,
                                now + UPLOAD_SESSION_TTL, now)
        self.store.save_resource("upload_sessions", session)
        self._audit(auth, "upload_session.created", "upload_session", session.id)
        self._remember(auth, idempotency_key, payload, {"id": session.id}, status=201)
        return session

    def upload_content(self, auth: AuthContext, session_id: str, content: bytes) -> UploadSession:
        require_scope(auth, Scope.DOCUMENTS_WRITE)
        session = self.store.get_resource("upload_sessions", session_id)
        require_owner(auth, session.owner_id)
        if not isinstance(content, bytes):
            raise UploadSessionError(422, "VALIDATION_ERROR", "binary request body is required")
        if len(content) > MAX_UPLOAD_BYTES:
            raise UploadSessionError(413, "UPLOAD_TOO_LARGE", "upload exceeds the supported size limit")
        # Verify bytes before any object-store write; never include digests or bytes in errors/audit.
        if len(content) != session.size_bytes or hashlib.sha256(content).hexdigest() != session.sha256:
            raise UploadSessionError(422, "UPLOAD_INTEGRITY_MISMATCH", "upload size or checksum does not match")
        # A completed same-byte PUT remains safe to retry even after session expiry.
        if session.status == UploadStatus.VERIFIED:
            return session
        if self.clock() >= session.expires_at:
            raise UploadSessionError(410, "UPLOAD_EXPIRED", "upload session has expired")
        document = self.store.get_resource("documents", session.document_id)
        if document.version != session.document_version or document.status != DocumentStatus.UPLOADED:
            raise UploadSessionError(409, "UPLOAD_SESSION_CONFLICT", "document changed after upload session creation")
        # The generated key is opaque and internal. Provider failures leave the session pending.
        try:
            if self.object_store is None:
                raise UploadSessionError(503, "DEPENDENCY_UNAVAILABLE", "object store is unavailable")
            object_key = self.object_store.put(f"uploads/{session.id}", content, media_type=session.media_type)
        except DependencyUnavailableError as exc:
            raise UploadSessionError(503, "DEPENDENCY_UNAVAILABLE", "object store is unavailable") from exc
        verified = replace(session, status=UploadStatus.VERIFIED, verified_at=self.clock(), object_key=object_key)
        self.store.save_resource("upload_sessions", verified)
        self._audit(auth, "upload_session.verified", "upload_session", session.id)
        return verified

    def list_documents(self, auth: AuthContext) -> list[Document]:
        require_scope(auth, Scope.DOCUMENTS_READ)
        return [document for document in self.store.list_resources("documents") if document.owner_id == auth.subject_id or PrincipalRole.REVIEWER in auth.roles or PrincipalRole.SERVICE in auth.roles]

    def get_document(self, auth: AuthContext, document_id: str) -> Document:
        require_scope(auth, Scope.DOCUMENTS_READ)
        document = self.store.get_resource("documents", document_id)
        require_owner(auth, document.owner_id)
        return document

    def enqueue_processing(
        self,
        auth: AuthContext,
        *,
        document_id: str,
        job_type: JobType,
        idempotency_key: str,
    ) -> UploadProcessingJob:
        require_scope(auth, Scope.DOCUMENTS_WRITE)
        job_type = JobType(job_type)
        document = self.store.get_resource("documents", document_id)
        require_owner(auth, document.owner_id)
        payload = {"document_id": document_id, "job_type": job_type.value}
        replay = self._idempotent(auth, idempotency_key, payload)
        if replay is not None:
            return self.store.get_resource("jobs", replay["value"]["id"])
        now = self.clock()
        job = UploadProcessingJob(self._id(), auth.subject_id, document_id, job_type, idempotency_key=idempotency_key, created_at=now, updated_at=now)
        self.job_queue.enqueue(job.id, {"document_id": document_id, "job_type": job_type.value})
        self.store.save_resource("jobs", job)
        self.store.save_resource("documents", replace(document, status=DocumentStatus.PROCESSING, version=document.version + 1, updated_at=now), expected_version=document.version)
        self._audit(auth, "upload_processing.queued", "upload_processing_job", job.id, job_type=job_type.value)
        self._remember(auth, idempotency_key, payload, {"id": job.id}, status=202)
        return job

    def complete_processing(self, auth: AuthContext, job_id: str, *, success: bool, error_code: str | None = None) -> UploadProcessingJob:
        require_role(auth, PrincipalRole.SERVICE)
        job = self.store.get_resource("jobs", job_id)
        now = self.clock()
        status = JobStatus.SUCCEEDED if success else JobStatus.FAILED
        updated = replace(job, status=status, attempt=job.attempt + 1, error_code=error_code, updated_at=now)
        self.store.save_resource("jobs", updated)
        document = self.store.get_resource("documents", job.document_id)
        self.store.save_resource("documents", replace(document, status=DocumentStatus.READY if success else DocumentStatus.FAILED, version=document.version + 1, updated_at=now), expected_version=document.version)
        self._audit(auth, "upload_processing.completed", "upload_processing_job", job_id, status=status.value)
        return updated

    def create_fact(
        self,
        auth: AuthContext,
        *,
        label: str,
        value: str,
        source_ref: str,
        source_type: SourceType,
        confidence: float,
        document_id: str | None = None,
        topic_id: str | None = None,
        idempotency_key: str,
    ) -> Fact:
        require_scope(auth, Scope.FACTS_WRITE)
        source_type = SourceType(source_type)
        if source_type == SourceType.USER_INPUT and confidence < 1.0:
            raise ServiceError("user_input facts must have confidence 1.0")
        if source_type != SourceType.USER_INPUT and not source_ref:
            raise ServiceError("non-user facts require source_ref")
        payload = {"label": label, "value": value, "source_ref": source_ref, "source_type": source_type.value, "confidence": confidence, "document_id": document_id, "topic_id": topic_id}
        replay = self._idempotent(auth, idempotency_key, payload)
        if replay is not None:
            return self.store.get_resource("facts", replay["value"]["id"])
        now = self.clock()
        fact = Fact(self._id(), auth.subject_id, label, value, source_ref, source_type, confidence, document_id=document_id, topic_id=topic_id, created_at=now, updated_at=now)
        self.store.save_resource("facts", fact)
        self._audit(auth, "fact.created", "fact", fact.id, source_type=source_type.value, review_status=fact.review_status.value)
        self._remember(auth, idempotency_key, payload, {"id": fact.id})
        return fact

    def list_facts(self, auth: AuthContext) -> list[Fact]:
        require_scope(auth, Scope.FACTS_READ)
        return [fact for fact in self.store.list_resources("facts") if fact.owner_id == auth.subject_id or PrincipalRole.REVIEWER in auth.roles or PrincipalRole.SERVICE in auth.roles]

    def review_fact(self, auth: AuthContext, fact_id: str, *, review_status: ReviewStatus, expected_version: int) -> Fact:
        require_scope(auth, Scope.FACTS_WRITE)
        review_status = ReviewStatus(review_status)
        require_role(auth, PrincipalRole.PATIENT, PrincipalRole.REVIEWER)
        fact = self.store.get_resource("facts", fact_id)
        require_owner(auth, fact.owner_id)
        if review_status == ReviewStatus.CONFIRMED and not fact.source_ref:
            raise ServiceError("cannot confirm a fact without source_ref")
        now = self.clock()
        updated = replace(fact, review_status=review_status, version=fact.version + 1, updated_at=now)
        self.store.save_resource("facts", updated, expected_version=expected_version)
        self._audit(auth, "fact.reviewed", "fact", fact_id, review_status=review_status.value)
        return updated

    @staticmethod
    def _created_order(items: list[Any]) -> list[Any]:
        """Return creation chronology with an ID tie-breaker for deterministic pages."""
        return sorted(items, key=lambda item: (item.created_at, item.id))

    @staticmethod
    def _visible(auth: AuthContext, owner_id: str) -> bool:
        return owner_id == auth.subject_id or PrincipalRole.REVIEWER in auth.roles or PrincipalRole.SERVICE in auth.roles

    def list_topics(self, auth: AuthContext) -> list[Topic]:
        require_scope(auth, Scope.VISITS_READ)
        return self._created_order([topic for topic in self.store.list_resources("topics") if self._visible(auth, topic.owner_id)])

    def list_visits(self, auth: AuthContext) -> list[Visit]:
        require_scope(auth, Scope.VISITS_READ)
        return self._created_order([visit for visit in self.store.list_resources("visits") if self._visible(auth, visit.owner_id)])

    def list_tasks(self, auth: AuthContext) -> list[Task]:
        require_scope(auth, Scope.TASKS_READ)
        return self._created_order([task for task in self.store.list_resources("tasks") if self._visible(auth, task.owner_id)])

    def create_topic(self, auth: AuthContext, *, name: str, idempotency_key: str) -> Topic:
        require_scope(auth, Scope.VISITS_WRITE)
        payload = {"name": name}
        replay = self._idempotent(auth, idempotency_key, payload)
        if replay is not None:
            return self.store.get_resource("topics", replay["value"]["id"])
        topic = Topic(self._id(), auth.subject_id, name, created_at=self.clock(), updated_at=self.clock())
        self.store.save_resource("topics", topic)
        self._audit(auth, "topic.created", "topic", topic.id)
        self._remember(auth, idempotency_key, payload, {"id": topic.id})
        return topic

    def create_visit(self, auth: AuthContext, *, title: str, starts_at: datetime | None, topic_ids: tuple[str, ...], idempotency_key: str) -> Visit:
        require_scope(auth, Scope.VISITS_WRITE)
        payload = {"title": title, "starts_at": starts_at, "topic_ids": topic_ids}
        replay = self._idempotent(auth, idempotency_key, payload)
        if replay is not None:
            return self.store.get_resource("visits", replay["value"]["id"])
        visit = Visit(self._id(), auth.subject_id, title, starts_at, topic_ids, created_at=self.clock(), updated_at=self.clock())
        self.store.save_resource("visits", visit)
        self._audit(auth, "visit.created", "visit", visit.id)
        self._remember(auth, idempotency_key, payload, {"id": visit.id})
        return visit

    def create_task(self, auth: AuthContext, *, title: str, visit_id: str | None, due_at: datetime | None, idempotency_key: str) -> Task:
        require_scope(auth, Scope.TASKS_WRITE)
        payload = {"title": title, "visit_id": visit_id, "due_at": due_at}
        replay = self._idempotent(auth, idempotency_key, payload)
        if replay is not None:
            return self.store.get_resource("tasks", replay["value"]["id"])
        task = Task(self._id(), auth.subject_id, title, visit_id=visit_id, due_at=due_at, created_at=self.clock(), updated_at=self.clock())
        self.store.save_resource("tasks", task)
        self._audit(auth, "task.created", "task", task.id)
        self._remember(auth, idempotency_key, payload, {"id": task.id})
        return task

    def create_share(self, auth: AuthContext, *, resource_type: str, resource_id: str, resource_version: int, expires_at: datetime, idempotency_key: str) -> tuple[ShareVersion, str]:
        require_scope(auth, Scope.SHARES_CREATE)
        if expires_at <= self.clock():
            raise ServiceError("share expiry must be in the future")
        resource = self._resource(resource_type, resource_id)
        require_owner(auth, resource.owner_id)
        if resource_version != getattr(resource, "version", 1):
            raise ServiceError("share resource_version must match the latest available immutable version")
        payload = {"resource_type": resource_type, "resource_id": resource_id, "resource_version": resource_version, "expires_at": expires_at}
        replay = self._idempotent(auth, idempotency_key, payload)
        if replay is not None:
            share = self.store.get_resource("shares", replay["value"]["id"])
            token = self._ephemeral_share_tokens.get(share.id)
            if token is None:
                raise ServiceError("share idempotency replay is unavailable after the ephemeral token vault was restarted")
            return share, token
        token = secrets.token_urlsafe(32)
        share = ShareVersion(self._id(), auth.subject_id, resource_type, resource_id, resource_version, expires_at, hashlib.sha256(token.encode()).hexdigest(), created_at=self.clock())
        self.store.save_resource("shares", share)
        self._ephemeral_share_tokens[share.id] = token
        self._audit(auth, "share.created", "share_version", share.id, shared_resource_type=resource_type)
        self._remember(auth, idempotency_key, payload, {"id": share.id, "token_digest": share.token_digest})
        return share, token

    def revoke_share(self, auth: AuthContext, share_id: str) -> ShareVersion:
        require_scope(auth, Scope.SHARES_REVOKE)
        share = self.store.get_resource("shares", share_id)
        require_owner(auth, share.owner_id)
        if share.status == ShareStatus.REVOKED:
            return share
        revoked = replace(share, status=ShareStatus.REVOKED, revoked_at=self.clock())
        self.store.save_resource("shares", revoked)
        self._audit(auth, "share.revoked", "share_version", share_id)
        return revoked

    def access_share(self, token: str) -> tuple[ShareVersion, Any]:
        digest = hashlib.sha256(token.encode()).hexdigest()
        for share in self.store.list_resources("shares"):
            if share.token_digest != digest:
                continue
            status = share.effective_status(self.clock())
            if status != ShareStatus.ACTIVE:
                raise ShareAccessError(f"share is {status.value}; downloaded copies cannot be recalled")
            return share, self._resource(share.resource_type, share.resource_id)
        raise ShareAccessError("share token is invalid")

    def list_audit(self, auth: AuthContext, *, resource_id: str | None = None) -> list[AuditEvent]:
        require_scope(auth, Scope.AUDIT_READ)
        require_role(auth, PrincipalRole.PATIENT, PrincipalRole.REVIEWER, PrincipalRole.SERVICE)
        events = self.store.list_audit_events()
        if resource_id is not None:
            events = [event for event in events if event.resource_id == resource_id]
        return [event for event in events if PrincipalRole.REVIEWER in auth.roles or PrincipalRole.SERVICE in auth.roles or event.actor_id == auth.subject_id]

    def _resource(self, resource_type: str, resource_id: str) -> Any:
        resource_types = {"document": "documents", "fact": "facts", "topic": "topics", "visit": "visits", "task": "tasks"}
        if resource_type not in resource_types:
            raise ServiceError(f"unsupported share resource_type: {resource_type}")
        return self.store.get_resource(resource_types[resource_type], resource_id)
