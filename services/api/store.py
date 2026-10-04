"""Provider-neutral metadata boundary and the in-memory test implementation."""
from __future__ import annotations

import collections.abc
import json
import sqlite3
import types
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, TypeVar, Union, get_args, get_origin, get_type_hints, runtime_checkable


from .dependencies import DependencyUnavailableError
from .sqlite_schema import UnsupportedSchemaVersionError, ensure_schema_version
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
    to_jsonable,
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


_MODEL_TYPES: dict[str, type[Any]] = {
    "documents": Document,
    "facts": Fact,
    "topics": Topic,
    "visits": Visit,
    "tasks": Task,
    "shares": ShareVersion,
    "jobs": UploadProcessingJob,
    "upload_sessions": UploadSession,
}


def _encode_storage(value: Any) -> Any:
    """Encode contract values while retaining private fields for durable storage."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {field.name: _encode_storage(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, collections.abc.Mapping):
        return {str(key): _encode_storage(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_encode_storage(item) for item in value]
    return value


def _decode_storage(value: Any, annotation: Any) -> Any:
    if value is None:
        return None
    if annotation is Any:
        return value
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (Union, types.UnionType):
        for candidate in args:
            if candidate is type(None):
                continue
            try:
                return _decode_storage(value, candidate)
            except (TypeError, ValueError):
                continue
        return value
    if origin is tuple:
        item_type = args[0] if args else Any
        return tuple(_decode_storage(item, item_type) for item in value)
    if origin is list:
        item_type = args[0] if args else Any
        return [_decode_storage(item, item_type) for item in value]
    if origin is not None and isinstance(origin, type) and issubclass(origin, collections.abc.Mapping):
        value_type = args[1] if len(args) > 1 else Any
        return {str(key): _decode_storage(item, value_type) for key, item in value.items()}
    if annotation is datetime:
        return datetime.fromisoformat(value)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return annotation(value)
    if isinstance(annotation, type) and is_dataclass(annotation):
        hints = get_type_hints(annotation)
        return annotation(**{
            field.name: _decode_storage(value[field.name], hints[field.name])
            for field in fields(annotation)
            if field.name in value
        })
    return value


def _decode_model(resource_type: str, payload: str) -> Any:
    model_type = _MODEL_TYPES.get(resource_type)
    if model_type is None:
        raise ValueError("unsupported metadata resource type")
    return _decode_storage(json.loads(payload), model_type)


class SQLiteMetadataStore:
    """Restart-safe local/staging adapter for the MetadataStore protocol.

    The adapter uses SQLite only as a durable boundary test. Production PHI
    requires an encrypted managed database and a reviewed migration process;
    callers can replace this class without changing ApiService.
    """

    def __init__(self, path: str | Path, *, available: bool = True) -> None:
        self.path = str(path)
        self.available = available
        self._connection: sqlite3.Connection | None = None
        if self.available:
            try:
                self._connection = sqlite3.connect(self.path, check_same_thread=False)
                self._initialize()
            except (OSError, sqlite3.Error, UnsupportedSchemaVersionError) as exc:
                self.close()
                raise DependencyUnavailableError("metadata store is unavailable") from exc

    def _initialize(self) -> None:
        connection = self._require_connection()

        def initialize(connection: sqlite3.Connection) -> None:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS resources (
                    resource_type TEXT NOT NULL,
                    identifier TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (resource_type, identifier)
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    identifier TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS idempotency (
                    actor_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (actor_id, idempotency_key)
                );
                """
            )

        ensure_schema_version(connection, current_version=1, initialize=initialize)

    def _require_connection(self) -> sqlite3.Connection:
        if not self.available or self._connection is None:
            raise DependencyUnavailableError("metadata store is unavailable")
        return self._connection

    def _collection_name(self, resource_type: str) -> str:
        if resource_type not in _MODEL_TYPES:
            raise ValueError("unsupported metadata resource type")
        return resource_type

    def is_ready(self) -> bool:
        if not self.available or self._connection is None:
            return False
        try:
            self._connection.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def get_resource(self, resource_type: str, identifier: str) -> Any:
        connection = self._require_connection()
        self._collection_name(resource_type)
        row = connection.execute(
            "SELECT payload FROM resources WHERE resource_type = ? AND identifier = ?",
            (resource_type, identifier),
        ).fetchone()
        if row is None:
            raise NotFoundError("resource not found")
        return _decode_model(resource_type, row[0])

    def list_resources(self, resource_type: str) -> list[Any]:
        connection = self._require_connection()
        self._collection_name(resource_type)
        rows = connection.execute(
            "SELECT payload FROM resources WHERE resource_type = ? ORDER BY identifier",
            (resource_type,),
        ).fetchall()
        return [_decode_model(resource_type, row[0]) for row in rows]

    def save_resource(self, resource_type: str, value: Any, expected_version: int | None = None) -> Any:
        connection = self._require_connection()
        self._collection_name(resource_type)
        identifier = getattr(value, "id", None)
        if not identifier:
            raise ValueError("resource id is required")
        version = int(getattr(value, "version", 1))
        owner_id = str(getattr(value, "owner_id", ""))
        payload = json.dumps(_encode_storage(value), sort_keys=True, separators=(",", ":"))
        with connection:
            row = connection.execute(
                "SELECT version FROM resources WHERE resource_type = ? AND identifier = ?",
                (resource_type, identifier),
            ).fetchone()
            if row is not None:
                actual_version = int(row[0])
                if expected_version is not None and actual_version != expected_version:
                    raise VersionConflictError("expected version does not match current version")
                if version <= actual_version:
                    raise VersionConflictError("updated version must be greater than current version")
                connection.execute(
                    "UPDATE resources SET owner_id = ?, version = ?, payload = ? WHERE resource_type = ? AND identifier = ?",
                    (owner_id, version, payload, resource_type, identifier),
                )
            else:
                if expected_version not in (None, 0):
                    raise VersionConflictError("expected version supplied for a new resource")
                connection.execute(
                    "INSERT INTO resources(resource_type, identifier, owner_id, version, payload) VALUES (?, ?, ?, ?, ?)",
                    (resource_type, identifier, owner_id, version, payload),
                )
        return value

    def append_audit(self, event: AuditEvent) -> None:
        connection = self._require_connection()
        with connection:
            connection.execute(
                "INSERT INTO audit_events(identifier, payload) VALUES (?, ?)",
                (event.id, json.dumps(_encode_storage(event), sort_keys=True, separators=(",", ":"))),
            )

    def list_audit_events(self) -> list[AuditEvent]:
        connection = self._require_connection()
        rows = connection.execute("SELECT payload FROM audit_events ORDER BY identifier").fetchall()
        return [_decode_storage(json.loads(row[0]), AuditEvent) for row in rows]

    def remember_idempotency(self, record: IdempotencyRecord) -> None:
        connection = self._require_connection()
        with connection:
            connection.execute(
                "INSERT OR REPLACE INTO idempotency(actor_id, idempotency_key, payload) VALUES (?, ?, ?)",
                (record.actor_id, record.key, json.dumps(_encode_storage(record), sort_keys=True, separators=(",", ":"))),
            )

    def get_idempotency(self, actor_id: str, key: str) -> IdempotencyRecord | None:
        connection = self._require_connection()
        row = connection.execute(
            "SELECT payload FROM idempotency WHERE actor_id = ? AND idempotency_key = ?",
            (actor_id, key),
        ).fetchone()
        return None if row is None else _decode_storage(json.loads(row[0]), IdempotencyRecord)

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "SQLiteMetadataStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
