"""Provider-neutral metadata boundary and the in-memory test implementation."""
from __future__ import annotations

from typing import Any, Protocol, TypeVar, runtime_checkable

from .dependencies import DependencyUnavailableError
from .models import (
    AuditEvent,
    Document,
    Fact,
    IdempotencyRecord,
    ShareVersion,
    Task,
    Topic,
    UploadProcessingJob,
    UploadSession,
    Visit,
)

T = TypeVar("T")


class NotFoundError(LookupError):
    pass


class VersionConflictError(RuntimeError):
    pass


class IdempotencyConflictError(RuntimeError):
    pass


@runtime_checkable
class MetadataStore(Protocol):
    """Minimum metadata/version/idempotency/audit contract used by ApiService.

    Implementations may use a database, an API, or another provider. The service
    never relies on provider-specific collections or transaction primitives.
    """

    def is_ready(self) -> bool:
        """Return false until the provider can serve metadata requests."""

    def get_resource(self, resource_type: str, identifier: str) -> Any:
        """Read one provider-owned resource within the service boundary."""

    def list_resources(self, resource_type: str) -> list[Any]:
        """List resources; the service applies authorization and ordering."""

    def save_resource(self, resource_type: str, value: Any, expected_version: int | None = None) -> Any:
        """Create or version-save one resource, enforcing optimistic conflicts."""

    def append_audit(self, event: AuditEvent) -> None:
        """Persist PHI-safe scalar audit metadata."""

    def list_audit_events(self) -> list[AuditEvent]:
        """Read audit metadata for service-side authorization filtering."""

    def remember_idempotency(self, record: IdempotencyRecord) -> None:
        """Persist one actor-scoped idempotency receipt."""

    def get_idempotency(self, actor_id: str, key: str) -> IdempotencyRecord | None:
        """Read one actor-scoped idempotency receipt."""


class InMemoryStore:
    """Explicitly non-persistent adapter; replace behind ``MetadataStore`` later."""

    _collections = {
        "documents": "documents",
        "facts": "facts",
        "topics": "topics",
        "visits": "visits",
        "tasks": "tasks",
        "shares": "shares",
        "jobs": "jobs",
        "upload_sessions": "upload_sessions",
    }

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.documents: dict[str, Document] = {}
        self.facts: dict[str, Fact] = {}
        self.topics: dict[str, Topic] = {}
        self.visits: dict[str, Visit] = {}
        self.tasks: dict[str, Task] = {}
        self.shares: dict[str, ShareVersion] = {}
        self.jobs: dict[str, UploadProcessingJob] = {}
        self.upload_sessions: dict[str, UploadSession] = {}
        self.audit_events: list[AuditEvent] = []
        self.idempotency: dict[tuple[str, str], IdempotencyRecord] = {}

    def is_ready(self) -> bool:
        return self.available

    def _ensure_available(self) -> None:
        if not self.available:
            raise DependencyUnavailableError("metadata store is unavailable")

    def _collection(self, resource_type: str) -> dict[str, Any]:
        self._ensure_available()
        name = self._collections.get(resource_type)
        if name is None:
            raise ValueError(f"unsupported metadata resource type: {resource_type}")
        return getattr(self, name)

    def get_resource(self, resource_type: str, identifier: str) -> Any:
        return self.get(self._collection(resource_type), identifier)

    def list_resources(self, resource_type: str) -> list[Any]:
        return list(self._collection(resource_type).values())

    def save_resource(self, resource_type: str, value: Any, expected_version: int | None = None) -> Any:
        return self.put(self._collection(resource_type), value, expected_version=expected_version)

    def append_audit(self, event: AuditEvent) -> None:
        self._ensure_available()
        self.audit_events.append(event)

    def list_audit_events(self) -> list[AuditEvent]:
        self._ensure_available()
        return list(self.audit_events)

    def put(self, collection: dict[str, T], value: T, expected_version: int | None = None) -> T:
        identifier = getattr(value, "id")
        existing = collection.get(identifier)
        if existing is not None:
            actual_version = getattr(existing, "version", 1)
            if expected_version is not None and actual_version != expected_version:
                raise VersionConflictError(f"expected version {expected_version}, found {actual_version}")
            if hasattr(value, "version") and getattr(value, "version") <= actual_version:
                raise VersionConflictError("updated version must be greater than current version")
        elif expected_version not in (None, 0):
            raise VersionConflictError("expected version supplied for a new resource")
        collection[identifier] = value
        return value

    def get(self, collection: dict[str, T], identifier: str) -> T:
        try:
            return collection[identifier]
        except KeyError as exc:
            raise NotFoundError(f"resource not found: {identifier}") from exc

    def remember_idempotency(self, record: IdempotencyRecord) -> None:
        self._ensure_available()
        self.idempotency[(record.actor_id, record.key)] = record

    def get_idempotency(self, actor_id: str, key: str) -> IdempotencyRecord | None:
        self._ensure_available()
        return self.idempotency.get((actor_id, key))
