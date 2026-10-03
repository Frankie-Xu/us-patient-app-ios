"""Typed, dependency-light domain models for the patient app service boundary.

The HTTP adapter may use Pydantic/FastAPI, but the core contract deliberately
uses stdlib dataclasses so validation and service tests are runnable offline.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


class ContractError(ValueError):
    """Raised when a request would violate the service contract."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_non_empty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a non-empty string")
    return value


def _validate_timestamp(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ContractError(f"{name} must include a timezone")
    return value


class SourceType(str, Enum):
    UPLOADED_DOCUMENT = "uploaded_document"
    USER_INPUT = "user_input"
    OCR = "ocr"
    EHR_IMPORT = "ehr_import"
    AI_EXTRACTION = "ai_extraction"
    TRANSLATION = "translation"
    OTHER = "other"


class ReviewStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    IN_REVIEW = "in_review"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    DELETED = "deleted"


class JobType(str, Enum):
    OCR = "ocr"
    EXTRACT_FACTS = "extract_facts"
    TRANSLATE = "translate"
    RENDER_SHARE = "render_share"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ShareStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class TaskStatus(str, Enum):
    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"


class PrincipalRole(str, Enum):
    PATIENT = "patient"
    CLINICIAN = "clinician"
    REVIEWER = "reviewer"
    SERVICE = "service"


class Scope(str, Enum):
    DOCUMENTS_READ = "documents:read"
    DOCUMENTS_WRITE = "documents:write"
    FACTS_READ = "facts:read"
    FACTS_WRITE = "facts:write"
    VISITS_READ = "visits:read"
    VISITS_WRITE = "visits:write"
    TASKS_READ = "tasks:read"
    TASKS_WRITE = "tasks:write"
    SHARES_CREATE = "shares:create"
    SHARES_REVOKE = "shares:revoke"
    AUDIT_READ = "audit:read"


@dataclass(frozen=True)
class AuthContext:
    subject_id: str
    roles: frozenset[PrincipalRole] = frozenset({PrincipalRole.PATIENT})
    scopes: frozenset[Scope] = frozenset()
    request_id: str = "local-request"

    def __post_init__(self) -> None:
        _require_non_empty(self.subject_id, "subject_id")
        _require_non_empty(self.request_id, "request_id")

    def can(self, scope: Scope) -> bool:
        return scope in self.scopes


@dataclass(frozen=True)
class Document:
    id: str
    owner_id: str
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    source_type: SourceType = SourceType.UPLOADED_DOCUMENT
    status: DocumentStatus = DocumentStatus.UPLOADED
    version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.id, "id")
        _require_non_empty(self.owner_id, "owner_id")
        _require_non_empty(self.filename, "filename")
        _require_non_empty(self.media_type, "media_type")
        if self.size_bytes < 0:
            raise ContractError("size_bytes must be non-negative")
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256.lower()):
            raise ContractError("sha256 must be a lowercase or uppercase 64-character hex digest")
        if self.version < 1:
            raise ContractError("version must be >= 1")
        _validate_timestamp(self.created_at, "created_at")
        _validate_timestamp(self.updated_at, "updated_at")


@dataclass(frozen=True)
class Fact:
    id: str
    owner_id: str
    label: str
    value: str
    source_ref: str
    source_type: SourceType
    confidence: float
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    document_id: str | None = None
    topic_id: str | None = None
    version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for field_name in ("id", "owner_id", "label", "value", "source_ref"):
            _require_non_empty(getattr(self, field_name), field_name)
        if not 0.0 <= self.confidence <= 1.0:
            raise ContractError("confidence must be between 0 and 1")
        if self.review_status == ReviewStatus.CONFIRMED and not self.source_ref:
            raise ContractError("confirmed facts require source_ref")
        if self.version < 1:
            raise ContractError("version must be >= 1")
        _validate_timestamp(self.created_at, "created_at")
        _validate_timestamp(self.updated_at, "updated_at")


@dataclass(frozen=True)
class Topic:
    id: str
    owner_id: str
    name: str
    version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for field_name in ("id", "owner_id", "name"):
            _require_non_empty(getattr(self, field_name), field_name)
        if self.version < 1:
            raise ContractError("version must be >= 1")


@dataclass(frozen=True)
class Visit:
    id: str
    owner_id: str
    title: str
    starts_at: datetime | None = None
    topic_ids: tuple[str, ...] = ()
    version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for field_name in ("id", "owner_id", "title"):
            _require_non_empty(getattr(self, field_name), field_name)
        if self.starts_at is not None:
            _validate_timestamp(self.starts_at, "starts_at")
        if self.version < 1:
            raise ContractError("version must be >= 1")


@dataclass(frozen=True)
class Task:
    id: str
    owner_id: str
    title: str
    visit_id: str | None = None
    status: TaskStatus = TaskStatus.OPEN
    due_at: datetime | None = None
    version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for field_name in ("id", "owner_id", "title"):
            _require_non_empty(getattr(self, field_name), field_name)
        if self.due_at is not None:
            _validate_timestamp(self.due_at, "due_at")
        if self.version < 1:
            raise ContractError("version must be >= 1")


@dataclass(frozen=True)
class ShareVersion:
    id: str
    owner_id: str
    resource_type: str
    resource_id: str
    resource_version: int
    expires_at: datetime
    token_digest: str
    status: ShareStatus = ShareStatus.ACTIVE
    revoked_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for field_name in ("id", "owner_id", "resource_type", "resource_id", "token_digest"):
            _require_non_empty(getattr(self, field_name), field_name)
        if self.resource_version < 1:
            raise ContractError("resource_version must be >= 1")
        _validate_timestamp(self.expires_at, "expires_at")
        _validate_timestamp(self.created_at, "created_at")
        if self.revoked_at is not None:
            _validate_timestamp(self.revoked_at, "revoked_at")

    def effective_status(self, now: datetime | None = None) -> ShareStatus:
        now = now or utc_now()
        if self.status == ShareStatus.REVOKED:
            return ShareStatus.REVOKED
        if now >= self.expires_at:
            return ShareStatus.EXPIRED
        return ShareStatus.ACTIVE


@dataclass(frozen=True)
class AuditEvent:
    id: str
    actor_id: str
    action: str
    resource_type: str
    resource_id: str
    request_id: str
    occurred_at: datetime = field(default_factory=utc_now)
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("id", "actor_id", "action", "resource_type", "resource_id", "request_id"):
            _require_non_empty(getattr(self, field_name), field_name)
        _validate_timestamp(self.occurred_at, "occurred_at")
        for key, value in self.metadata.items():
            _require_non_empty(str(key), "metadata key")
            _require_non_empty(str(value), "metadata value")


@dataclass(frozen=True)
class UploadProcessingJob:
    id: str
    owner_id: str
    document_id: str
    job_type: JobType
    status: JobStatus = JobStatus.QUEUED
    idempotency_key: str = ""
    attempt: int = 0
    error_code: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for field_name in ("id", "owner_id", "document_id", "idempotency_key"):
            _require_non_empty(getattr(self, field_name), field_name)
        if self.attempt < 0:
            raise ContractError("attempt must be non-negative")


@dataclass(frozen=True)
class IdempotencyRecord:
    key: str
    actor_id: str
    request_hash: str
    response_status: int
    response_body: Mapping[str, Any]
    created_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None


def to_jsonable(value: Any) -> Any:
    """Serialize contract values without leaking private token material."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        result = {key: to_jsonable(item) for key, item in asdict(value).items()}
        if isinstance(value, ShareVersion):
            result.pop("token_digest", None)
        return result
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]
    return value
