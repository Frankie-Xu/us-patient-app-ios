"""Application service implementing the initial API contract."""
from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from dataclasses import replace
from datetime import datetime
from typing import Any, Callable, Mapping

from .auth import require_owner, require_role, require_scope
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
    Visit,
    utc_now,
)
from .store import IdempotencyConflictError, InMemoryStore, NotFoundError, VersionConflictError


class ServiceError(RuntimeError):
    pass


class ShareAccessError(ServiceError):
    pass


class ApiService:
    """Use-case boundary with explicit auth, audit and PHI-safe adapters."""

    def __init__(self, store: InMemoryStore | None = None, clock: Callable[[], datetime] = utc_now) -> None:
        self.store = store or InMemoryStore()
        self.clock = clock
        # Raw share tokens live only in this process memory for idempotent replay.
        # The store receives only a digest, so a durable adapter never persists a token.
        self._ephemeral_share_tokens: dict[str, str] = {}

    def _id(self) -> str:
        return str(uuid.uuid4())

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
        self.store.audit_events.append(event)

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
        payload = {"filename": filename, "media_type": media_type, "size_bytes": size_bytes, "sha256": sha256}
        replay = self._idempotent(auth, idempotency_key, payload)
        if replay is not None:
            return self.store.get(self.store.documents, replay["value"]["id"])
        document = Document(self._id(), auth.subject_id, filename, media_type, size_bytes, sha256, created_at=self.clock(), updated_at=self.clock())
        self.store.put(self.store.documents, document)
        self._audit(auth, "document.created", "document", document.id)
        self._remember(auth, idempotency_key, payload, {"id": document.id})
        return document

    def list_documents(self, auth: AuthContext) -> list[Document]:
        require_scope(auth, Scope.DOCUMENTS_READ)
        return [document for document in self.store.documents.values() if document.owner_id == auth.subject_id or PrincipalRole.REVIEWER in auth.roles or PrincipalRole.SERVICE in auth.roles]

    def get_document(self, auth: AuthContext, document_id: str) -> Document:
        require_scope(auth, Scope.DOCUMENTS_READ)
        document = self.store.get(self.store.documents, document_id)
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
        document = self.store.get(self.store.documents, document_id)
        require_owner(auth, document.owner_id)
        payload = {"document_id": document_id, "job_type": job_type.value}
        replay = self._idempotent(auth, idempotency_key, payload)
        if replay is not None:
            return self.store.get(self.store.jobs, replay["value"]["id"])
        now = self.clock()
        job = UploadProcessingJob(self._id(), auth.subject_id, document_id, job_type, idempotency_key=idempotency_key, created_at=now, updated_at=now)
        self.store.jobs[job.id] = job
        self.store.documents[document_id] = replace(document, status=DocumentStatus.PROCESSING, version=document.version + 1, updated_at=now)
        self._audit(auth, "upload_processing.queued", "upload_processing_job", job.id, job_type=job_type.value)
        self._remember(auth, idempotency_key, payload, {"id": job.id}, status=202)
        return job

    def complete_processing(self, auth: AuthContext, job_id: str, *, success: bool, error_code: str | None = None) -> UploadProcessingJob:
        require_role(auth, PrincipalRole.SERVICE)
        job = self.store.get(self.store.jobs, job_id)
        now = self.clock()
        status = JobStatus.SUCCEEDED if success else JobStatus.FAILED
        updated = replace(job, status=status, attempt=job.attempt + 1, error_code=error_code, updated_at=now)
        self.store.jobs[job_id] = updated
        document = self.store.get(self.store.documents, job.document_id)
        self.store.documents[document.id] = replace(document, status=DocumentStatus.READY if success else DocumentStatus.FAILED, version=document.version + 1, updated_at=now)
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
            return self.store.get(self.store.facts, replay["value"]["id"])
        now = self.clock()
        fact = Fact(self._id(), auth.subject_id, label, value, source_ref, source_type, confidence, document_id=document_id, topic_id=topic_id, created_at=now, updated_at=now)
        self.store.facts[fact.id] = fact
        self._audit(auth, "fact.created", "fact", fact.id, source_type=source_type.value, review_status=fact.review_status.value)
        self._remember(auth, idempotency_key, payload, {"id": fact.id})
        return fact

    def list_facts(self, auth: AuthContext) -> list[Fact]:
        require_scope(auth, Scope.FACTS_READ)
        return [fact for fact in self.store.facts.values() if fact.owner_id == auth.subject_id or PrincipalRole.REVIEWER in auth.roles or PrincipalRole.SERVICE in auth.roles]

    def review_fact(self, auth: AuthContext, fact_id: str, *, review_status: ReviewStatus, expected_version: int) -> Fact:
        require_scope(auth, Scope.FACTS_WRITE)
        review_status = ReviewStatus(review_status)
        require_role(auth, PrincipalRole.PATIENT, PrincipalRole.REVIEWER)
        fact = self.store.get(self.store.facts, fact_id)
        require_owner(auth, fact.owner_id)
        if review_status == ReviewStatus.CONFIRMED and not fact.source_ref:
            raise ServiceError("cannot confirm a fact without source_ref")
        now = self.clock()
        updated = replace(fact, review_status=review_status, version=fact.version + 1, updated_at=now)
        self.store.put(self.store.facts, updated, expected_version=expected_version)
        self._audit(auth, "fact.reviewed", "fact", fact_id, review_status=review_status.value)
        return updated

    def create_topic(self, auth: AuthContext, *, name: str, idempotency_key: str) -> Topic:
        require_scope(auth, Scope.VISITS_WRITE)
        payload = {"name": name}
        replay = self._idempotent(auth, idempotency_key, payload)
        if replay is not None:
            return self.store.get(self.store.topics, replay["value"]["id"])
        topic = Topic(self._id(), auth.subject_id, name, created_at=self.clock(), updated_at=self.clock())
        self.store.topics[topic.id] = topic
        self._audit(auth, "topic.created", "topic", topic.id)
        self._remember(auth, idempotency_key, payload, {"id": topic.id})
        return topic

    def create_visit(self, auth: AuthContext, *, title: str, starts_at: datetime | None, topic_ids: tuple[str, ...], idempotency_key: str) -> Visit:
        require_scope(auth, Scope.VISITS_WRITE)
        payload = {"title": title, "starts_at": starts_at, "topic_ids": topic_ids}
        replay = self._idempotent(auth, idempotency_key, payload)
        if replay is not None:
            return self.store.get(self.store.visits, replay["value"]["id"])
        visit = Visit(self._id(), auth.subject_id, title, starts_at, topic_ids, created_at=self.clock(), updated_at=self.clock())
        self.store.visits[visit.id] = visit
        self._audit(auth, "visit.created", "visit", visit.id)
        self._remember(auth, idempotency_key, payload, {"id": visit.id})
        return visit

    def create_task(self, auth: AuthContext, *, title: str, visit_id: str | None, due_at: datetime | None, idempotency_key: str) -> Task:
        require_scope(auth, Scope.TASKS_WRITE)
        payload = {"title": title, "visit_id": visit_id, "due_at": due_at}
        replay = self._idempotent(auth, idempotency_key, payload)
        if replay is not None:
            return self.store.get(self.store.tasks, replay["value"]["id"])
        task = Task(self._id(), auth.subject_id, title, visit_id=visit_id, due_at=due_at, created_at=self.clock(), updated_at=self.clock())
        self.store.tasks[task.id] = task
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
            share = self.store.get(self.store.shares, replay["value"]["id"])
            token = self._ephemeral_share_tokens.get(share.id)
            if token is None:
                raise ServiceError("share idempotency replay is unavailable after the ephemeral token vault was restarted")
            return share, token
        token = secrets.token_urlsafe(32)
        share = ShareVersion(self._id(), auth.subject_id, resource_type, resource_id, resource_version, expires_at, hashlib.sha256(token.encode()).hexdigest(), created_at=self.clock())
        self.store.shares[share.id] = share
        self._ephemeral_share_tokens[share.id] = token
        self._audit(auth, "share.created", "share_version", share.id, shared_resource_type=resource_type)
        self._remember(auth, idempotency_key, payload, {"id": share.id, "token_digest": share.token_digest})
        return share, token

    def revoke_share(self, auth: AuthContext, share_id: str) -> ShareVersion:
        require_scope(auth, Scope.SHARES_REVOKE)
        share = self.store.get(self.store.shares, share_id)
        require_owner(auth, share.owner_id)
        if share.status == ShareStatus.REVOKED:
            return share
        revoked = replace(share, status=ShareStatus.REVOKED, revoked_at=self.clock())
        self.store.shares[share_id] = revoked
        self._audit(auth, "share.revoked", "share_version", share_id)
        return revoked

    def access_share(self, token: str) -> tuple[ShareVersion, Any]:
        digest = hashlib.sha256(token.encode()).hexdigest()
        for share in self.store.shares.values():
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
        events = self.store.audit_events
        if resource_id is not None:
            events = [event for event in events if event.resource_id == resource_id]
        return [event for event in events if PrincipalRole.REVIEWER in auth.roles or PrincipalRole.SERVICE in auth.roles or event.actor_id == auth.subject_id]

    def _resource(self, resource_type: str, resource_id: str) -> Any:
        collections = {"document": self.store.documents, "fact": self.store.facts, "topic": self.store.topics, "visit": self.store.visits, "task": self.store.tasks}
        if resource_type not in collections:
            raise ServiceError(f"unsupported share resource_type: {resource_type}")
        return self.store.get(collections[resource_type], resource_id)
