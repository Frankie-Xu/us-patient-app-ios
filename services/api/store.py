"""In-memory adapters used by the initial service skeleton and tests."""
from __future__ import annotations

from typing import TypeVar

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


class InMemoryStore:
    """Explicitly non-persistent adapter; replace behind this interface later."""

    def __init__(self) -> None:
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
        self.idempotency[(record.actor_id, record.key)] = record

    def get_idempotency(self, actor_id: str, key: str) -> IdempotencyRecord | None:
        return self.idempotency.get((actor_id, key))
